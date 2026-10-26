(() => {
  const modal = document.getElementById("dashboard-qr-modal");
  const openButton = document.querySelector("[data-qr-scan-open]");
  if (!modal || !openButton) return;

  const dialog = modal.querySelector(".dashboard-qr-modal");
  const frame = modal.querySelector(".qr-camera-frame");
  const video = document.getElementById("dashboard-qr-video");
  const status = document.getElementById("dashboard-qr-status");
  const startButton = document.getElementById("dashboard-qr-camera-start");
  const imageInput = document.getElementById("dashboard-qr-image");
  const manualForm = document.getElementById("dashboard-qr-manual");
  const manualValue = document.getElementById("dashboard-qr-value");
  let stream = null;
  let detector = null;
  let scanTimer = null;
  let navigating = false;
  const canvas = document.createElement("canvas");
  const canvasContext = canvas.getContext("2d", { willReadFrequently: true });

  const setStatus = (message, kind = "") => {
    status.textContent = message;
    status.className = `qr-scanner-status ${kind}`.trim();
  };

  const targetFromValue = (value) => {
    const raw = String(value || "").trim();
    if (/^[1-9]\d*$/.test(raw)) return `/q/exchangers/${Number(raw)}`;
    try {
      const parsed = new URL(raw, window.location.origin);
      const match = parsed.pathname.match(/^\/q\/exchangers\/([1-9]\d*)\/?$/);
      return match ? `/q/exchangers/${Number(match[1])}` : null;
    } catch (_error) {
      return null;
    }
  };

  const stopCamera = () => {
    if (scanTimer) window.clearTimeout(scanTimer);
    scanTimer = null;
    if (stream) stream.getTracks().forEach((track) => track.stop());
    stream = null;
    video.srcObject = null;
    frame.classList.remove("active");
    startButton.disabled = false;
  };

  const openTarget = (value) => {
    const target = targetFromValue(value);
    if (!target) {
      const preview = String(value || "").trim().slice(0, 80);
      setStatus(`QR은 읽었지만 열교환기 ID가 아닙니다. 판독값: ${preview || "(빈 값)"}`, "error");
      return false;
    }
    navigating = true;
    setStatus("QR-code를 확인했습니다. 열교환기 정보를 여는 중입니다.", "success");
    stopCamera();
    window.location.assign(target);
    return true;
  };

  const ensureDecoder = () => {
    if ("BarcodeDetector" in window && !detector) {
      try {
        detector = new BarcodeDetector({ formats: ["qr_code"] });
      } catch (_error) {
        detector = null;
      }
    }
    if (!detector && typeof window.jsQR !== "function") {
      throw new Error("QR 판독기를 불러오지 못했습니다. 화면을 새로고침해 주세요.");
    }
  };

  const loadImageFile = async (file) => {
    if (typeof createImageBitmap === "function") {
      try {
        const bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
        return { source: bitmap, width: bitmap.width, height: bitmap.height, close: () => bitmap.close() };
      } catch (_error) {
        // Some mobile browsers expose createImageBitmap but reject camera files.
        // Fall through to the HTMLImageElement decoder.
      }
    }
    const objectUrl = URL.createObjectURL(file);
    try {
      const image = new Image();
      image.src = objectUrl;
      if (typeof image.decode === "function") {
        await image.decode();
      } else {
        await new Promise((resolve, reject) => {
          image.onload = resolve;
          image.onerror = () => reject(new Error("선택한 사진 형식을 브라우저에서 열 수 없습니다."));
        });
      }
      return { source: image, width: image.naturalWidth, height: image.naturalHeight, close: () => URL.revokeObjectURL(objectUrl) };
    } catch (error) {
      URL.revokeObjectURL(objectUrl);
      throw error;
    }
  };

  const decodeWithJsQr = (source, sourceWidth, sourceHeight) => {
    if (typeof window.jsQR !== "function" || !canvasContext || !sourceWidth || !sourceHeight) return null;
    const attempts = [
      { x: 0.5, y: 0.5, crop: 1, maximumSide: 1200 },
      { x: 0.5, y: 0.5, crop: 1, maximumSide: 2400 },
      { x: 0.5, y: 0.5, crop: 0.72, maximumSide: 1800 },
      { x: 0.5, y: 0.5, crop: 0.48, maximumSide: 1600 },
      { x: 0.3, y: 0.3, crop: 0.58, maximumSide: 1800 },
      { x: 0.7, y: 0.3, crop: 0.58, maximumSide: 1800 },
      { x: 0.3, y: 0.7, crop: 0.58, maximumSide: 1800 },
      { x: 0.7, y: 0.7, crop: 0.58, maximumSide: 1800 },
    ];
    for (const attempt of attempts) {
      const cropWidth = Math.max(1, Math.round(sourceWidth * attempt.crop));
      const cropHeight = Math.max(1, Math.round(sourceHeight * attempt.crop));
      const sourceX = Math.max(0, Math.min(sourceWidth - cropWidth, Math.round(sourceWidth * attempt.x - cropWidth / 2)));
      const sourceY = Math.max(0, Math.min(sourceHeight - cropHeight, Math.round(sourceHeight * attempt.y - cropHeight / 2)));
      const scale = Math.min(1, attempt.maximumSide / Math.max(cropWidth, cropHeight));
      canvas.width = Math.max(1, Math.round(cropWidth * scale));
      canvas.height = Math.max(1, Math.round(cropHeight * scale));
      canvasContext.clearRect(0, 0, canvas.width, canvas.height);
      canvasContext.drawImage(
        source,
        sourceX,
        sourceY,
        cropWidth,
        cropHeight,
        0,
        0,
        canvas.width,
        canvas.height,
      );
      const pixels = canvasContext.getImageData(0, 0, canvas.width, canvas.height);
      const result = window.jsQR(pixels.data, pixels.width, pixels.height, {
        inversionAttempts: "attemptBoth",
      });
      if (result?.data) return result.data;
    }
    return null;
  };

  const decodeSource = async (source, sourceWidth, sourceHeight) => {
    ensureDecoder();
    if (detector) {
      try {
        const codes = await detector.detect(source);
        if (codes.length) return codes[0].rawValue;
      } catch (_error) {
        // Continue with the local image-data decoder.
      }
    }
    return decodeWithJsQr(source, sourceWidth, sourceHeight);
  };

  const scanVideo = async () => {
    if (!stream || navigating) return;
    try {
      const value = await decodeSource(video, video.videoWidth, video.videoHeight);
      if (value && openTarget(value)) return;
    } catch (_error) {
      // A frame can fail while the camera is focusing; keep scanning.
    }
    scanTimer = window.setTimeout(scanVideo, 280);
  };

  const startCamera = async () => {
    stopCamera();
    navigating = false;
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
      setStatus("HTTP 접속에서는 실시간 카메라가 제한됩니다. 사진 촬영 방식으로 전환합니다.");
      imageInput.click();
      return;
    }
    startButton.disabled = true;
    setStatus("카메라 사용 권한을 확인하고 있습니다.");
    try {
      ensureDecoder();
      stream = await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: { facingMode: { ideal: "environment" } },
      });
      video.srcObject = stream;
      await video.play();
      frame.classList.add("active");
      setStatus("QR-code를 사각형 안에 맞춰주세요.");
      scanVideo();
    } catch (error) {
      stopCamera();
      setStatus(`${error?.message || "카메라를 시작하지 못했습니다."} 사진에서 읽기를 이용해 주세요.`, "error");
    }
  };

  const close = () => {
    stopCamera();
    modal.hidden = true;
    document.body.style.overflow = "";
    openButton.focus();
  };

  openButton.addEventListener("click", () => {
    navigating = false;
    modal.hidden = false;
    document.body.style.overflow = "hidden";
    setStatus("대기 중");
    dialog?.focus();
  });
  startButton.addEventListener("click", startCamera);
  modal.querySelectorAll("[data-qr-scan-close]").forEach((button) => button.addEventListener("click", close));
  modal.addEventListener("click", (event) => { if (event.target === modal) close(); });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !modal.hidden) close();
  });
  manualForm.addEventListener("submit", (event) => {
    event.preventDefault();
    openTarget(manualValue.value);
  });
  imageInput.addEventListener("change", async () => {
    const file = imageInput.files?.[0];
    if (!file) return;
    if (file.type && !file.type.startsWith("image/")) {
      setStatus("이미지 파일만 선택할 수 있습니다.", "error");
      imageInput.value = "";
      return;
    }
    setStatus("사진의 QR-code를 확인하고 있습니다.");
    try {
      ensureDecoder();
      const image = await loadImageFile(file);
      const value = await decodeSource(image.source, image.width, image.height);
      image.close();
      if (!value) {
        setStatus("사진에서 유효한 열교환기 QR-code를 찾지 못했습니다.", "error");
      } else {
        openTarget(value);
      }
    } catch (error) {
      setStatus(`${error?.message || "사진을 판독하지 못했습니다."} JPEG 또는 PNG 사진으로 다시 시도해 주세요.`, "error");
    } finally {
      imageInput.value = "";
    }
  });
})();
