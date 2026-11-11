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
    const reason = typeof message === "string" ? message.replace(/[\u0000-\u001f\u007f]/g, " ").replace(/\s+/g, " ").trim().slice(0, 300) : "";
    this.stop();
    this.failure = reason || "Camera capture failed. Retry the camera when ready.";
    this.status.textContent = this.failure;
    this.reportFailure(this.failure);
  }
  async start(session, settings, generation) {
    this.status.textContent = "Waiting for camera permission…";
    if (!navigator.mediaDevices?.getUserMedia) {
      this.fail("Camera access requires localhost or HTTPS in a supported browser.", generation);
      return;
    }
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        video: {width: {ideal: settings.width}, height: {ideal: settings.height}}, audio: false
      });
    } catch (error) {
      const messages = {
        NotAllowedError: "Camera permission denied. Allow camera access for this site and retry.",
        NotFoundError: "No camera found. Connect a camera and retry.",
        NotReadableError: "Camera could not start. Close other apps using it and retry.",
        OverconstrainedError: "Camera capture settings could not be satisfied. Lower camera dimensions and retry.",
        SecurityError: "Camera access is blocked by page security settings. Use localhost or HTTPS and retry.",
        AbortError: "Camera startup was interrupted. Keep this tab visible and retry."
      };
      this.fail(messages[error?.name] || "Camera access could not start. Check the browser camera settings and retry.", generation);
      return;
    }
    // A late permission grant must not reopen a cancelled session.
    if (generation !== this.generation) {
      stream.getTracks().forEach((track) => track.stop());
      return;
    }
    this.stream = stream;
    stream.getVideoTracks().forEach((track) => {
      track.onended = () => this.fail("Camera disconnected or permission revoked. Reconnect it and retry.", generation);
    });
    this.status.textContent = "Camera access granted · starting preview…";
    try {
      this.video.muted = true;
      this.video.playsInline = true;
      this.video.srcObject = stream;
    } catch {
      this.fail("Camera access was granted, but the preview could not attach the video stream. Refresh the page and retry.", generation);
      return;
    }
    try {
      await this.video.play();
    } catch (error) {
      this.fail(error?.name === "NotAllowedError" ?
        "Camera permission was granted, but video playback was blocked. Keep this Pomo tab visible and retry." :
        "Camera access was granted, but preview playback could not start. Keep this Pomo tab visible and retry.", generation);
      return;
    }
    if (generation !== this.generation) return;
    this.status.textContent = "Camera preview started · preparing first frame…";
    let canvas, context;
    try {
      canvas = document.createElement("canvas");
      context = canvas.getContext("2d");
      if (!context) throw new Error("unavailable");
    } catch {
      this.fail("Camera preview started, but frame encoding is unavailable in this browser. Refresh the page and retry.", generation);
      return;
    }
    let sequence = 0;
    const sample = async () => {
      if (generation !== this.generation) return;
      let stage = "encoding", upload;
      try {
        if (this.video.readyState < 2 || !this.video.videoWidth || !this.video.videoHeight) {
          this.status.textContent = "Camera preview is waiting for a video frame…";
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
        if (!blob || !Number.isFinite(blob.size) || blob.size <= 0) {
          this.fail("Camera preview started, but JPEG encoding returned no frame. Refresh the page and retry.", generation);
          return;
        }
        if (blob.size > settings.max_bytes) {
          this.fail("Camera JPEG exceeds the configured upload limit. Lower camera dimensions or JPEG quality and retry.", generation);
          return;
        }
        stage = "upload";
        upload = new AbortController();
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
          if (!response.ok) {
            const status = Number.isSafeInteger(response.status) ? response.status : "unknown";
            this.fail(`Camera upload rejected (${status}). Check backend logs and retry.`, generation);
            return;
          }
          stage = "response";
          result = await response.json();
          if (generation !== this.generation) return;
          if (!Number.isSafeInteger(result?.sequence) || result.sequence < 0) throw new Error("invalid response");
        } finally {
          clearTimeout(timeout);
          if (this.upload === upload) this.upload = null;
        }
        this.status.textContent = `Camera active · frame ${result.sequence + 1} received`;
        // Schedule only after completion: no old-frame backlog or overlapping uploads.
        this.timer = setTimeout(sample, 1000 / settings.fps);
      } catch {
        const message = stage === "encoding" ?
          "Camera preview started, but JPEG frame encoding failed. Refresh the page and retry." :
          upload?.signal.aborted ? "Camera frame upload timed out. Check backend logs and retry." :
          stage === "response" ? "Camera upload received an invalid backend response. Refresh the page and retry." :
          "Camera frame upload failed before completion. Check the connection and backend logs, then retry.";
        this.fail(message, generation);
      }
    };
    sample();
  }
}
