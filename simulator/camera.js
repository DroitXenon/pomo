"use strict";
class CameraController {
  constructor(video, status, reportFailure) {
    this.video = video;
    this.status = status;
    this.reportFailure = reportFailure;
    this.generation = 0;
    this.session = null;
  }
  stop() {
    this.generation++;
    clearTimeout(this.timer);
    this.upload?.abort();
    this.upload = null;
    this.stream?.getTracks().forEach((track) => { track.onended = null; track.stop(); });
    this.stream = null;
    if (this.video.srcObject !== null) this.video.srcObject = null;
    this.session = null;
  }
  update(state) {
    const active = state.powered_on === true && state.monitoring_enabled === true && state.input_source === "camera";
    const session = active && state.camera_processor_ready === true ? state.camera_session : null;
    if (!session) {
      this.stop();
      this.status.textContent = state.input_source !== "camera" ? "Camera off · simulated input selected" :
        !state.powered_on ? "Camera off" :
        !state.camera_processor_ready ? "Camera processor unavailable · check backend logs" :
        state.camera_capture_status === "unavailable" ? (this.failure || "Camera unavailable · retry camera when ready") :
        state.monitoring_enabled ? "Camera active in another tab" : "Camera paused";
      return;
    }
    if (session === this.session) return;
    this.stop();
    this.failure = null;
    this.session = session;
    this.start(session, state.camera_settings, this.generation);
  }
  fail(message, generation) {
    if (generation !== this.generation) return;
    this.stop();
    this.failure = message;
    this.status.textContent = message;
    this.reportFailure(message);
  }
  async start(session, settings, generation) {
    this.status.textContent = "Waiting for camera permission…";
    try {
      if (!navigator.mediaDevices?.getUserMedia) {
        throw new Error("Camera access requires localhost or HTTPS in a supported browser");
      }
      const stream = await navigator.mediaDevices.getUserMedia({
        video: {width: {ideal: settings.width}, height: {ideal: settings.height}}, audio: false
      });
      // A late permission grant must not reopen a cancelled session.
      if (generation !== this.generation) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      this.stream = stream;
      stream.getVideoTracks().forEach((track) => {
        track.onended = () => this.fail("Camera disconnected or permission revoked", generation);
      });
      this.video.srcObject = stream;
      await this.video.play();
      if (generation !== this.generation) return;
      const canvas = document.createElement("canvas");
      const context = canvas.getContext("2d");
      let sequence = 0;
      const sample = async () => {
        if (generation !== this.generation) return;
        try {
          if (this.video.readyState < 2 || !this.video.videoWidth) {
            this.timer = setTimeout(sample, 100);
            return;
          }
          const scale = Math.min(1, settings.width / this.video.videoWidth,
                                 settings.height / this.video.videoHeight);
          canvas.width = Math.max(1, Math.floor(this.video.videoWidth * scale));
          canvas.height = Math.max(1, Math.floor(this.video.videoHeight * scale));
          context.drawImage(this.video, 0, 0, canvas.width, canvas.height);
          const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", settings.jpeg_quality));
          if (generation !== this.generation) return;
          if (!blob || blob.size > settings.max_bytes) throw new Error("Camera frame exceeds upload limit");
          const upload = new AbortController();
          this.upload = upload;
          const timeout = setTimeout(() => upload.abort(), settings.timeout_seconds * 1000);
          let result;
          try {
            const response = await fetch("camera/frame", {
              method: "POST", body: blob, signal: upload.signal,
              headers: {"Content-Type": "image/jpeg", "X-Camera-Session": session,
                        "X-Frame-Sequence": String(sequence++)}
            });
            if (generation !== this.generation) return;
            if (!response.ok) throw new Error(`Camera upload rejected (${response.status})`);
            result = await response.json();
            if (generation !== this.generation) return;
          } finally {
            clearTimeout(timeout);
            if (this.upload === upload) this.upload = null;
          }
          this.status.textContent = `Camera active · frame ${result.sequence + 1} received`;
          // Schedule only after completion: no old-frame backlog or overlapping uploads.
          this.timer = setTimeout(sample, 1000 / settings.fps);
        } catch (error) { this.fail(error.message || "Camera upload failed", generation); }
      };
      sample();
    } catch (error) {
      const messages = {
        NotAllowedError: "Camera permission denied · allow camera access and retry",
        NotFoundError: "No camera found",
        NotReadableError: "Camera could not start · check whether another app is using it"
      };
      this.fail(messages[error.name] || error.message, generation);
    }
  }
}
