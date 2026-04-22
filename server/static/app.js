const apiBase = "/api";

const state = {
  token: localStorage.getItem("token") || "",
  me: null,
  newWorkshopImageDataUrl: "",
  newProfileAvatarDataUrl: "",
  reviewMediaDataUrls: [],
  pendingVerifyEmail: localStorage.getItem("pending_verify_email") || "",
};

const WORKSHOP_TYPE_OPTIONS = ["Групповой МК", "Индивидуальный МК", "МК-Свидание"];
const MAX_REVIEW_MEDIA_FILES = 3;
let masterCabinetRefreshTimer = null;

function qs(id) {
  return document.querySelector(id);
}

function show(message) {
  const text = String(message || "");
  let container = document.querySelector(".toast-container");
  if (!container) {
    container = document.createElement("div");
    container.className = "toast-container";
    document.body.appendChild(container);
  }

  const toast = document.createElement("div");
  toast.className = "toast";
  toast.textContent = text;
  container.appendChild(toast);

  setTimeout(() => {
    toast.classList.add("hide");
    setTimeout(() => toast.remove(), 220);
  }, 2800);
}

function localizeErrorMessage(message) {
  const msg = String(message || "");
  const map = [
    { match: "Not authenticated", text: "Сначала войдите в аккаунт." },
    { match: "Invalid token", text: "Сессия истекла. Войдите заново." },
    { match: "you already have booking/queue for this slot", text: "Вы уже записаны или стоите в очереди на этот слот." },
    { match: "slot not found", text: "Слот не найден." },
    { match: "slot is not available", text: "Слот недоступен." },
    { match: "booking not found", text: "Запись не найдена." },
    { match: "invalid credentials", text: "Неверная почта или пароль." },
    { match: "email not verified", text: "Сначала подтвердите почту кодом из письма." },
    { match: "too many code attempts", text: "Слишком много неверных попыток. Попробуйте снова через 15 минут." },
    { match: "title required", text: "Укажи название мастер-класса." },
    { match: "price, duration_min, capacity must be > 0", text: "Цена, длительность и количество человек должны быть больше 0." },
    { match: "price must be > 0", text: "Цена должна быть больше 0." },
    { match: "total_seats must be > 0", text: "Количество человек в слоте должно быть больше 0." },
    { match: "total_seats cannot be less than booked_seats", text: "Нельзя поставить мест меньше, чем уже забронировано." },
    { match: "slot has active bookings", text: "Нельзя удалить слот, пока в нем есть активные брони или очередь." },
    { match: "start_at required", text: "Выбери дату и время начала слота." },
    { match: "workshop duration must be > 0", text: "Сначала укажи длительность мастер-класса больше 0." },
    { match: "duration_min must be > 0", text: "Длительность мастер-класса должна быть больше 0." },
    { match: "workshop not found", text: "Мастер-класс не найден или не принадлежит вам." },
    { match: "slot not found", text: "Слот не найден." },
    { match: "booking allowed at least 24 hours before start", text: "Запись доступна минимум за 24 часа до начала мастер-класса." },
    { match: "reschedule allowed at least 24 hours before start", text: "Перенос доступен минимум за 24 часа до начала мастер-класса." },
    { match: "booking is not active", text: "Перенос доступен только для активной записи." },
    { match: "target_slot_id required", text: "Выберите новый слот для переноса." },
    { match: "target slot not found", text: "Выбранный слот не найден." },
    { match: "target slot must be different", text: "Выберите другой слот." },
    { match: "target slot must belong to same workshop", text: "Можно переносить только на слот этого же мастер-класса." },
    { match: "target slot is not available", text: "Этот слот уже недоступен." },
    { match: "not enough free seats in target slot", text: "В выбранном слоте недостаточно мест." },
    { match: "you already have booking history for target slot", text: "На этот слот уже была запись с вашего аккаунта. Выберите другой слот." },
    { match: "text required", text: "Введите текст отзыва." },
    { match: "rating must be from 1 to 5", text: "Оценка должна быть от 1 до 5." },
    { match: "review not found", text: "Отзыв не найден или не принадлежит текущему пользователю." },
    { match: "forbidden to reply", text: "Отвечать на отзыв может только мастер, которому этот отзыв оставили." },
    { match: "reply required", text: "Введите ответ на отзыв." },
    { match: "media must be list", text: "Некорректный формат медиа в отзыве." },
    { match: "too many media items", text: "Можно прикрепить не более 3 фото/видео." },
    { match: "only image/video data urls are allowed", text: "Разрешены только фото и видео файлы." },
    { match: "media item is too large", text: "Один из файлов слишком большой." },
    { match: "self review forbidden", text: "Нельзя оставить отзыв самому себе." },
    { match: "review allowed only for customer of this master", text: "Отзыв может оставить только человек, который был именно у этого мастера." },
    { match: "review allowed only after completed booking", text: "Оставить отзыв можно только после посещения мастер-класса." },
    { match: "review already exists for completed booking", text: "Все доступные отзывы этому мастеру уже оставлены." },
    { match: "review login required", text: "Войдите, чтобы оставить отзыв." },
  ];
  for (const item of map) {
    if (msg.includes(item.match)) return item.text;
  }
  return msg;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function imageBlock(imageUrl, className = "mk-photo", fallback = "МК") {
  const fallbackText = escapeHtml(fallback);
  if (imageUrl) {
    return `<div class="${className}" data-fallback="${fallbackText}"><img src="${escapeHtml(imageUrl)}" alt="Фото мастер-класса" loading="lazy" /></div>`;
  }
  return `<div class="${className}">${fallbackText}</div>`;
}

function avatarBlock(imageUrl, fallbackText = "ЛК") {
  if (imageUrl) {
    return `<img src="${escapeHtml(imageUrl)}" alt="Аватар" loading="lazy" />`;
  }
  return escapeHtml(fallbackText);
}

function autoFitAvatarImage(img) {
  if (!img || img.dataset.avatarAutofitBound === "1") return;
  img.dataset.avatarAutofitBound = "1";

  const analyzeAndScale = () => {
    if (!img.naturalWidth || !img.naturalHeight) return;
    try {
      const maxSide = 256;
      const ratio = Math.max(img.naturalWidth, img.naturalHeight) / maxSide;
      const w = Math.max(24, Math.round(img.naturalWidth / Math.max(1, ratio)));
      const h = Math.max(24, Math.round(img.naturalHeight / Math.max(1, ratio)));

      const canvas = document.createElement("canvas");
      canvas.width = w;
      canvas.height = h;
      const ctx = canvas.getContext("2d", { willReadFrequently: true });
      if (!ctx) return;
      ctx.drawImage(img, 0, 0, w, h);
      const px = ctx.getImageData(0, 0, w, h).data;

      const cornerAt = (x, y) => {
        const idx = (y * w + x) * 4;
        return [px[idx], px[idx + 1], px[idx + 2]];
      };
      const corners = [cornerAt(0, 0), cornerAt(w - 1, 0), cornerAt(0, h - 1), cornerAt(w - 1, h - 1)];
      const avg = corners.reduce((acc, c) => [acc[0] + c[0], acc[1] + c[1], acc[2] + c[2]], [0, 0, 0]).map((v) => v / corners.length);
      const spread = corners.reduce(
        (max, c) => Math.max(max, Math.abs(c[0] - avg[0]) + Math.abs(c[1] - avg[1]) + Math.abs(c[2] - avg[2])),
        0
      );
      if (spread > 90) return;

      const tolerance = 40;
      const isBorder = (x, y) => {
        const idx = (y * w + x) * 4;
        const a = px[idx + 3];
        if (a <= 12) return true;
        const d = Math.abs(px[idx] - avg[0]) + Math.abs(px[idx + 1] - avg[1]) + Math.abs(px[idx + 2] - avg[2]);
        return d <= tolerance;
      };

      let top = 0;
      let bottom = h - 1;
      let left = 0;
      let right = w - 1;

      while (top < h && Array.from({ length: w }).every((_, x) => isBorder(x, top))) top += 1;
      while (bottom >= 0 && Array.from({ length: w }).every((_, x) => isBorder(x, bottom))) bottom -= 1;
      while (left < w && Array.from({ length: h }).every((_, y) => isBorder(left, y))) left += 1;
      while (right >= 0 && Array.from({ length: h }).every((_, y) => isBorder(right, y))) right -= 1;

      if (right <= left || bottom <= top) return;
      const innerW = right - left + 1;
      const innerH = bottom - top + 1;
      const contentRatio = Math.max(innerW / w, innerH / h);

      if (contentRatio < 0.82) {
        const scale = Math.min(2.8, Math.max(1.1, 0.9 / Math.max(0.1, contentRatio)));
        img.style.transform = `scale(${scale.toFixed(2)})`;
        img.style.transformOrigin = "center center";
      } else {
        img.style.transform = "";
      }
    } catch {
    }
  };

  if (img.complete) {
    analyzeAndScale();
  } else {
    img.addEventListener("load", analyzeAndScale, { once: true });
  }
}

function applyImageFallbacks(root = document) {
  root.querySelectorAll(".mk-photo img, .avatar img, .review-avatar img, .nav-avatar img").forEach((img) => {
    if (img.dataset.fallbackBound === "1") return;
    img.dataset.fallbackBound = "1";
    img.addEventListener(
      "error",
      () => {
        const parent = img.parentElement;
        if (!parent) return;
        const fallback = parent.getAttribute("data-fallback") || "Фото";
        parent.classList.add("image-fallback");
        parent.textContent = fallback;
      },
      { once: true }
    );
    if (img.closest(".avatar")) {
      autoFitAvatarImage(img);
    }
  });
}

function normalizeRuPhone(value) {
  const digits = String(value || "").replace(/\D/g, "");
  if (!digits) return "+7";
  if (digits.startsWith("7")) return `+7${digits.slice(1, 11)}`;
  if (digits.startsWith("8")) return `+7${digits.slice(1, 11)}`;
  return `+7${digits.slice(0, 10)}`;
}

function normalizeWorkshopType(value) {
  const type = String(value || "").trim();
  if (WORKSHOP_TYPE_OPTIONS.includes(type)) return type;
  return WORKSHOP_TYPE_OPTIONS[0];
}

function workshopTypesList(value, fallbackValue = "") {
  const source = Array.isArray(value) ? value : String(value || "").split(",");
  const seen = new Set();

  source.forEach((raw) => {
    const text = String(raw || "").trim();
    if (!text) return;
    seen.add(normalizeWorkshopType(text));
  });

  if (!seen.size && fallbackValue) {
    const fallbackText = String(fallbackValue || "").trim();
    if (fallbackText) seen.add(normalizeWorkshopType(fallbackText));
  }

  const ordered = WORKSHOP_TYPE_OPTIONS.filter((item) => seen.has(item));
  return ordered;
}

function workshopTypesLabel(value, fallbackValue = "Творческий МК") {
  const types = workshopTypesList(value, fallbackValue);
  if (!types.length) return fallbackValue;
  return types.join(", ");
}

function capacityForWorkshopType(workshopType, fallbackValue = 1) {
  const type = normalizeWorkshopType(workshopType);
  if (type === "Индивидуальный МК") return 1;
  if (type === "МК-Свидание") return 2;
  const fallback = Number(fallbackValue);
  return Number.isFinite(fallback) && fallback > 0 ? fallback : 6;
}

function syncWorkshopCapacityControl(typeInput, capacityInput) {
  if (!typeInput || !capacityInput) return;
  const type = normalizeWorkshopType(typeInput.value);
  if (type === "Индивидуальный МК" || type === "МК-Свидание") {
    capacityInput.value = String(capacityForWorkshopType(type));
    capacityInput.readOnly = true;
    capacityInput.disabled = true;
    return;
  }
  if (!capacityInput.value || Number(capacityInput.value) <= 0) {
    capacityInput.value = "1";
  }
  capacityInput.readOnly = false;
  capacityInput.disabled = false;
}

function syncSlotSeatsByType(typeInput, seatsInput) {
  if (!typeInput || !seatsInput) return;
  const type = normalizeWorkshopType(typeInput.value);
  if (type === "Индивидуальный МК" || type === "МК-Свидание") {
    seatsInput.value = String(capacityForWorkshopType(type));
    seatsInput.readOnly = true;
    seatsInput.disabled = true;
    return;
  }
  if (!seatsInput.value || Number(seatsInput.value) <= 0) {
    seatsInput.value = "1";
  }
  seatsInput.readOnly = false;
  seatsInput.disabled = false;
}

function ensureWorkshopEditModal() {
  let modal = qs("#workshop-edit-modal");
  if (modal) return modal;

  modal = document.createElement("div");
  modal.id = "workshop-edit-modal";
  modal.className = "workshop-edit-modal";
  modal.hidden = true;
  modal.innerHTML = `
    <div class="workshop-edit-overlay" data-close-edit-modal="1"></div>
    <section class="card workshop-edit-card" role="dialog" aria-modal="true" aria-labelledby="workshop-edit-title">
      <div class="workshop-edit-head">
        <h3 id="workshop-edit-title">Редактировать мастер-класс</h3>
        <button type="button" class="button ghost" data-close-edit-modal="1">Закрыть</button>
      </div>
      <div class="workshop-edit-grid">
        <label class="field full"><span>Название</span><input id="edit-workshop-title" type="text" /></label>
        <label class="field"><span>Длительность (мин)</span><input id="edit-workshop-duration" type="number" min="1" step="1" /></label>
        <label class="field full"><span>Локация</span><input id="edit-workshop-location" type="text" /></label>
        <label class="field full"><span>Описание</span><textarea id="edit-workshop-description" rows="4"></textarea></label>
        <label class="field full"><span>Фото мастер-класса</span><input id="edit-workshop-image-file" type="file" accept="image/*" /></label>
        <div class="workshop-edit-photo-row full">
          <span id="edit-workshop-image-info" class="hint"></span>
          <button id="edit-workshop-remove-image" type="button" class="button ghost">Удалить фото</button>
        </div>
      </div>
      <p id="edit-workshop-status" class="hint workshop-edit-status"></p>
      <div class="workshop-edit-actions">
        <button id="edit-workshop-cancel" type="button" class="button ghost">Отмена</button>
        <button id="edit-workshop-save" type="button" class="button primary">Сохранить</button>
      </div>
    </section>
  `;

  document.body.appendChild(modal);
  return modal;
}

function openWorkshopEditModal(current) {
  const modal = ensureWorkshopEditModal();
  const titleInput = qs("#edit-workshop-title");
  const durationInput = qs("#edit-workshop-duration");
  const locationInput = qs("#edit-workshop-location");
  const descriptionInput = qs("#edit-workshop-description");
  const imageFileInput = qs("#edit-workshop-image-file");
  const imageInfo = qs("#edit-workshop-image-info");
  const removeImageBtn = qs("#edit-workshop-remove-image");
  const statusNode = qs("#edit-workshop-status");
  const saveBtn = qs("#edit-workshop-save");
  const cancelBtn = qs("#edit-workshop-cancel");
  const closeButtons = modal.querySelectorAll("[data-close-edit-modal='1']");

  let imageUrl = String(current.image_url || "").trim();
  let readingImage = false;

  titleInput.value = String(current.title || "");
  durationInput.value = String(Math.max(1, Number(current.duration_min || 0)));
  locationInput.value = String(current.location || "");
  descriptionInput.value = String(current.description || "");
  imageFileInput.value = "";
  imageInfo.textContent = imageUrl ? "Текущее фото установлено" : "Фото не установлено";
  statusNode.textContent = "";

  removeImageBtn.onclick = () => {
    imageUrl = "";
    imageFileInput.value = "";
    imageInfo.textContent = "Фото будет удалено";
  };

  imageFileInput.onchange = async (event) => {
    statusNode.textContent = "";
    const input = event.target;
    const file = input && input.files ? input.files[0] : null;
    if (!file) return;
    if (!file.type.startsWith("image/")) {
      imageFileInput.value = "";
      statusNode.textContent = "Выбери файл изображения";
      return;
    }
    if (file.size > 8 * 1024 * 1024) {
      imageFileInput.value = "";
      statusNode.textContent = "Фото слишком большое (максимум 8 МБ)";
      return;
    }
    try {
      readingImage = true;
      saveBtn.disabled = true;
      imageUrl = await readFileAsDataUrl(file);
      imageInfo.textContent = `Выбрано фото: ${file.name}`;
    } catch (error) {
      imageFileInput.value = "";
      statusNode.textContent = error.message || "Не удалось прочитать фото";
    } finally {
      readingImage = false;
      saveBtn.disabled = false;
    }
  };

  modal.hidden = false;
  document.body.classList.add("modal-open");

  return new Promise((resolve) => {
    let done = false;

    const close = (result = null) => {
      if (done) return;
      done = true;
      modal.hidden = true;
      document.body.classList.remove("modal-open");
      closeButtons.forEach((btn) => {
        btn.onclick = null;
      });
      cancelBtn.onclick = null;
      saveBtn.onclick = null;
      resolve(result);
    };

    closeButtons.forEach((btn) => {
      btn.onclick = () => close(null);
    });
    cancelBtn.onclick = () => close(null);

    saveBtn.onclick = () => {
      if (readingImage) {
        statusNode.textContent = "Дождись загрузки фото";
        return;
      }
      const title = titleInput.value.trim();
      const description = descriptionInput.value.trim();
      const location = locationInput.value.trim();
      const durationMin = Number(durationInput.value);

      if (!title) {
        statusNode.textContent = "Название не может быть пустым";
        return;
      }
      if (!Number.isFinite(durationMin) || durationMin <= 0) {
        statusNode.textContent = "Длительность должна быть больше 0";
        return;
      }

      close({
        title,
        description,
        location,
        duration_min: durationMin,
        image_url: imageUrl,
      });
    };
  });
}

function ensureSlotEditModal() {
  let modal = qs("#slot-edit-modal");
  if (modal) return modal;

  modal = document.createElement("div");
  modal.id = "slot-edit-modal";
  modal.className = "workshop-edit-modal";
  modal.hidden = true;
  modal.innerHTML = `
    <div class="workshop-edit-overlay" data-close-slot-modal="1"></div>
    <section class="card workshop-edit-card" role="dialog" aria-modal="true" aria-labelledby="slot-edit-title">
      <div class="workshop-edit-head">
        <h3 id="slot-edit-title">Редактировать слот</h3>
        <button type="button" class="button ghost" data-close-slot-modal="1">Закрыть</button>
      </div>
      <div class="workshop-edit-grid">
        <label class="field full"><span>Начало</span><input id="edit-slot-start" type="datetime-local" /></label>
        <label class="field"><span>Вид МК</span><select id="edit-slot-type"></select></label>
        <label class="field"><span>Цена (₽)</span><input id="edit-slot-price" type="number" min="1" step="1" /></label>
        <label class="field"><span>Количество человек</span><input id="edit-slot-seats" type="number" min="1" step="1" /></label>
      </div>
      <p id="edit-slot-status" class="hint workshop-edit-status"></p>
      <div class="workshop-edit-actions">
        <button id="edit-slot-cancel" type="button" class="button ghost">Отмена</button>
        <button id="edit-slot-save" type="button" class="button primary">Сохранить</button>
      </div>
    </section>
  `;
  document.body.appendChild(modal);
  return modal;
}

function openSlotEditModal(current) {
  const modal = ensureSlotEditModal();
  const startInput = qs("#edit-slot-start");
  const typeInput = qs("#edit-slot-type");
  const priceInput = qs("#edit-slot-price");
  const seatsInput = qs("#edit-slot-seats");
  const statusNode = qs("#edit-slot-status");
  const saveBtn = qs("#edit-slot-save");
  const cancelBtn = qs("#edit-slot-cancel");
  const closeButtons = modal.querySelectorAll("[data-close-slot-modal='1']");

  typeInput.innerHTML = WORKSHOP_TYPE_OPTIONS.map((option) => `<option value="${escapeHtml(option)}">${escapeHtml(option)}</option>`).join("");
  startInput.value = toLocalInputFromIso(current.start_at);
  typeInput.value = normalizeWorkshopType(current.workshop_type || "");
  priceInput.value = String(Math.max(1, Number(current.price || 0)));
  seatsInput.value = String(Math.max(1, Number(current.total_seats || 0)));
  syncSlotSeatsByType(typeInput, seatsInput);
  statusNode.textContent = "";

  typeInput.onchange = () => {
    syncSlotSeatsByType(typeInput, seatsInput);
  };

  modal.hidden = false;
  document.body.classList.add("modal-open");

  return new Promise((resolve) => {
    let done = false;
    const close = (result = null) => {
      if (done) return;
      done = true;
      modal.hidden = true;
      document.body.classList.remove("modal-open");
      closeButtons.forEach((btn) => {
        btn.onclick = null;
      });
      cancelBtn.onclick = null;
      saveBtn.onclick = null;
      resolve(result);
    };

    closeButtons.forEach((btn) => {
      btn.onclick = () => close(null);
    });
    cancelBtn.onclick = () => close(null);

    saveBtn.onclick = () => {
      const startAt = toIsoFromLocalInput(startInput.value);
      const workshopType = normalizeWorkshopType(typeInput.value);
      const price = Number(priceInput.value || 0);
      let seats = Number(seatsInput.value || 0);
      if (workshopType !== "Групповой МК") {
        seats = capacityForWorkshopType(workshopType);
      }

      if (!startAt) {
        statusNode.textContent = "Выбери корректные дату и время начала";
        return;
      }
      if (!Number.isFinite(price) || price <= 0) {
        statusNode.textContent = "Цена должна быть больше 0";
        return;
      }
      if (!Number.isFinite(seats) || seats <= 0) {
        statusNode.textContent = "Количество человек должно быть больше 0";
        return;
      }

      close({
        start_at: startAt,
        workshop_type: workshopType,
        price,
        total_seats: seats,
      });
    };
  });
}

async function collectReviewMediaFromFiles(files) {
  const selected = Array.from(files || []);
  if (!selected.length) return { ok: true, media: [] };
  if (selected.length > MAX_REVIEW_MEDIA_FILES) return { ok: false, error: "Можно выбрать максимум 3 файла" };

  const mediaItems = [];
  for (const file of selected) {
    const isMedia = file.type.startsWith("image/") || file.type.startsWith("video/");
    if (!isMedia) return { ok: false, error: "Разрешены только фото и видео" };
    if (file.size > 12 * 1024 * 1024) return { ok: false, error: "Файл больше 12MB. Выбери файл меньше." };
    const dataUrl = await readFileAsDataUrl(file).catch(() => "");
    if (!dataUrl) return { ok: false, error: "Не удалось прочитать файл" };
    mediaItems.push(dataUrl);
  }
  return { ok: true, media: mediaItems };
}

function renderReviewMediaPreview(node, mediaItems) {
  if (!node) return;
  if (Array.isArray(mediaItems) && mediaItems.length) {
    node.innerHTML = renderReviewMediaGallery(mediaItems);
    applyImageFallbacks(node);
    return;
  }
  node.innerHTML = '<p class="hint">Медиа не прикреплены</p>';
}

function ensureReviewEditModal() {
  let modal = qs("#review-edit-modal");
  if (modal) return modal;

  modal = document.createElement("div");
  modal.id = "review-edit-modal";
  modal.className = "workshop-edit-modal";
  modal.hidden = true;
  modal.innerHTML = `
    <div class="workshop-edit-overlay" data-close-review-edit-modal="1"></div>
    <section class="card workshop-edit-card" role="dialog" aria-modal="true" aria-labelledby="review-edit-title">
      <div class="workshop-edit-head">
        <h3 id="review-edit-title">Изменить отзыв</h3>
        <button type="button" class="button ghost" data-close-review-edit-modal="1">Закрыть</button>
      </div>
      <div class="workshop-edit-grid">
        <label class="field"><span>Оценка</span>
          <select id="review-edit-rating">
            <option value="5">5</option>
            <option value="4">4</option>
            <option value="3">3</option>
            <option value="2">2</option>
            <option value="1">1</option>
          </select>
        </label>
        <label class="field full"><span>Текст</span><textarea id="review-edit-text" rows="4"></textarea></label>
        <label class="field full"><span>Фото/видео</span><input id="review-edit-files" type="file" accept="image/*,video/*" multiple /></label>
        <div class="workshop-edit-photo-row full">
          <span id="review-edit-files-info" class="hint"></span>
          <button id="review-edit-clear-media" type="button" class="button ghost">Удалить медиа</button>
        </div>
        <div id="review-edit-media-preview" class="review-edit-media-preview full"></div>
      </div>
      <p id="review-edit-status" class="hint workshop-edit-status"></p>
      <div class="workshop-edit-actions">
        <button id="review-edit-cancel" type="button" class="button ghost">Отмена</button>
        <button id="review-edit-save" type="button" class="button primary">Сохранить</button>
      </div>
    </section>
  `;
  document.body.appendChild(modal);
  return modal;
}

function openReviewEditModal(current) {
  const modal = ensureReviewEditModal();
  const ratingInput = qs("#review-edit-rating");
  const textInput = qs("#review-edit-text");
  const filesInput = qs("#review-edit-files");
  const filesInfo = qs("#review-edit-files-info");
  const clearMediaBtn = qs("#review-edit-clear-media");
  const previewNode = qs("#review-edit-media-preview");
  const statusNode = qs("#review-edit-status");
  const saveBtn = qs("#review-edit-save");
  const cancelBtn = qs("#review-edit-cancel");
  const closeButtons = modal.querySelectorAll("[data-close-review-edit-modal='1']");

  ratingInput.value = String(Math.min(5, Math.max(1, Number(current.rating || 5))));
  textInput.value = String(current.text || "");
  filesInput.value = "";
  let mediaData = Array.isArray(current.media) ? current.media.slice(0, MAX_REVIEW_MEDIA_FILES) : [];
  filesInfo.textContent = mediaData.length ? `Текущих файлов: ${mediaData.length}` : "Фото/видео не прикреплены";
  renderReviewMediaPreview(previewNode, mediaData);
  statusNode.textContent = "";

  clearMediaBtn.onclick = () => {
    mediaData = [];
    filesInput.value = "";
    filesInfo.textContent = "Медиа будут удалены";
    renderReviewMediaPreview(previewNode, mediaData);
  };

  filesInput.onchange = async (event) => {
    statusNode.textContent = "";
    const selected = Array.from(event.target.files || []);
    if (!selected.length) return;
    saveBtn.disabled = true;
    const parsed = await collectReviewMediaFromFiles(selected);
    saveBtn.disabled = false;
    if (!parsed.ok) {
      filesInput.value = "";
      statusNode.textContent = parsed.error;
      return;
    }
    const merged = [...mediaData, ...parsed.media];
    if (merged.length > MAX_REVIEW_MEDIA_FILES) {
      statusNode.textContent = "Можно прикрепить не более 3 фото/видео";
      filesInput.value = "";
      return;
    }
    mediaData = merged;
    filesInfo.textContent = `Выбрано файлов: ${mediaData.length}`;
    renderReviewMediaPreview(previewNode, mediaData);
  };

  modal.hidden = false;
  document.body.classList.add("modal-open");

  return new Promise((resolve) => {
    let done = false;
    const close = (result = null) => {
      if (done) return;
      done = true;
      modal.hidden = true;
      document.body.classList.remove("modal-open");
      closeButtons.forEach((btn) => {
        btn.onclick = null;
      });
      cancelBtn.onclick = null;
      saveBtn.onclick = null;
      clearMediaBtn.onclick = null;
      filesInput.onchange = null;
      resolve(result);
    };

    closeButtons.forEach((btn) => {
      btn.onclick = () => close(null);
    });
    cancelBtn.onclick = () => close(null);

    saveBtn.onclick = () => {
      const rating = Number(ratingInput.value || 0);
      const text = textInput.value.trim();
      if (!Number.isFinite(rating) || rating < 1 || rating > 5) {
        statusNode.textContent = "Оценка должна быть от 1 до 5.";
        return;
      }
      if (!text) {
        statusNode.textContent = "Введите текст отзыва.";
        return;
      }
      close({
        rating,
        text,
        media: mediaData,
      });
    };
  });
}

function ensureBookingMoveModal() {
  let modal = qs("#booking-move-modal");
  if (modal) return modal;

  modal = document.createElement("div");
  modal.id = "booking-move-modal";
  modal.className = "workshop-edit-modal";
  modal.hidden = true;
  modal.innerHTML = `
    <div class="workshop-edit-overlay" data-close-booking-move-modal="1"></div>
    <section class="card workshop-edit-card" role="dialog" aria-modal="true" aria-labelledby="booking-move-title">
      <div class="workshop-edit-head">
        <h3 id="booking-move-title">Перенести запись</h3>
        <button type="button" class="button ghost" data-close-booking-move-modal="1">Закрыть</button>
      </div>
      <div class="workshop-edit-grid">
        <div id="booking-move-summary" class="booking-move-summary full"></div>
        <div id="booking-move-options" class="booking-move-options full"></div>
      </div>
      <p id="booking-move-status" class="hint workshop-edit-status"></p>
      <div class="workshop-edit-actions">
        <button id="booking-move-cancel" type="button" class="button ghost">Отмена</button>
        <button id="booking-move-save" type="button" class="button primary">Перенести</button>
      </div>
    </section>
  `;
  document.body.appendChild(modal);
  return modal;
}

function openBookingMoveModal(currentBooking, options) {
  const modal = ensureBookingMoveModal();
  const summaryNode = qs("#booking-move-summary");
  const optionsNode = qs("#booking-move-options");
  const statusNode = qs("#booking-move-status");
  const saveBtn = qs("#booking-move-save");
  const cancelBtn = qs("#booking-move-cancel");
  const closeButtons = modal.querySelectorAll("[data-close-booking-move-modal='1']");

  const title = String(currentBooking?.title || "Мастер-класс");
  const currentDate = currentBooking?.start_at ? new Date(currentBooking.start_at).toLocaleString("ru-RU") : "";
  const guests = Math.max(1, Number(currentBooking?.guests || 1));
  summaryNode.innerHTML = `
    <strong>${escapeHtml(title)}</strong>
    <span>Текущая запись: ${escapeHtml(currentDate)} · ${guests} гостей</span>
  `;

  const normalizedOptions = Array.isArray(options) ? options.filter(Boolean) : [];
  if (!normalizedOptions.length) {
    optionsNode.innerHTML = '<p class="hint">Нет подходящих слотов для переноса по этому МК.</p>';
    saveBtn.disabled = true;
  } else {
    optionsNode.innerHTML = normalizedOptions
      .map((slot, index) => {
        const slotId = Number(slot.id || 0);
        const startLabel = slot.start_at ? new Date(slot.start_at).toLocaleString("ru-RU") : "Без даты";
        const workshopType = normalizeWorkshopType(slot.workshop_type || "");
        const freeSeats = Math.max(0, Number(slot.free_seats ?? 0));
        const price = Math.max(0, Number(slot.price ?? 0));
        return `
          <label class="booking-move-option">
            <input type="radio" name="booking-move-slot" value="${slotId}" ${index === 0 ? "checked" : ""} />
            <div>
              <strong>${escapeHtml(startLabel)}</strong>
              <span>Вид МК: ${escapeHtml(workshopType)} · Свободно: ${freeSeats} · Цена: ${price} ₽</span>
            </div>
          </label>
        `;
      })
      .join("");
    saveBtn.disabled = false;
  }
  statusNode.textContent = "";

  modal.hidden = false;
  document.body.classList.add("modal-open");

  return new Promise((resolve) => {
    let done = false;
    const close = (result = null) => {
      if (done) return;
      done = true;
      modal.hidden = true;
      document.body.classList.remove("modal-open");
      closeButtons.forEach((btn) => {
        btn.onclick = null;
      });
      cancelBtn.onclick = null;
      saveBtn.onclick = null;
      saveBtn.disabled = false;
      resolve(result);
    };

    closeButtons.forEach((btn) => {
      btn.onclick = () => close(null);
    });
    cancelBtn.onclick = () => close(null);

    saveBtn.onclick = () => {
      const selected = modal.querySelector("input[name='booking-move-slot']:checked");
      const targetSlotId = Number(selected?.value || 0);
      if (targetSlotId <= 0) {
        statusNode.textContent = "Выберите слот для переноса";
        return;
      }
      close({ target_slot_id: targetSlotId });
    };
  });
}

function ensureSlotPeopleModal() {
  let modal = qs("#slot-people-modal");
  if (modal) return modal;

  modal = document.createElement("div");
  modal.id = "slot-people-modal";
  modal.className = "workshop-edit-modal";
  modal.hidden = true;
  modal.innerHTML = `
    <div class="workshop-edit-overlay" data-close-slot-people-modal="1"></div>
    <section class="card workshop-edit-card" role="dialog" aria-modal="true" aria-labelledby="slot-people-title">
      <div class="workshop-edit-head">
        <h3 id="slot-people-title">Записавшиеся люди</h3>
        <button type="button" class="button ghost" data-close-slot-people-modal="1">Закрыть</button>
      </div>
      <div class="workshop-edit-grid">
        <div id="slot-people-summary" class="booking-move-summary full"></div>
        <div id="slot-people-list" class="slot-people-list full"></div>
      </div>
      <div class="workshop-edit-actions">
        <button id="slot-people-close" type="button" class="button primary">Закрыть</button>
      </div>
    </section>
  `;
  document.body.appendChild(modal);
  return modal;
}

function openSlotPeopleModal(slot, peopleRows) {
  const modal = ensureSlotPeopleModal();
  const summaryNode = qs("#slot-people-summary");
  const listNode = qs("#slot-people-list");
  const closeBtn = qs("#slot-people-close");
  const closeButtons = modal.querySelectorAll("[data-close-slot-people-modal='1']");

  const title = String(slot?.workshop_title || "Мастер-класс");
  const slotDate = slot?.start_at ? new Date(slot.start_at).toLocaleString("ru-RU") : "";
  const slotType = normalizeWorkshopType(slot?.workshop_type || "");
  summaryNode.innerHTML = `
    <strong>${escapeHtml(title)}</strong>
    <span>${escapeHtml(slotDate)} · ${escapeHtml(slotType)} · Слот ID ${Number(slot?.id || 0)}</span>
  `;

  const rows = Array.isArray(peopleRows) ? peopleRows : [];
  listNode.innerHTML = rows.length
    ? rows
        .map((person) => {
          const personDate = new Date(person.created_at || person.updated_at || "").toLocaleString("ru-RU");
          return `
          <div class="queue-item">
            <div class="workshop-admin-meta">
              <strong>${escapeHtml(person.user_name || "Пользователь")}</strong>
              <span>${Number(person.guests || 0)} гостей · записан: ${escapeHtml(personDate)}</span>
            </div>
            <span class="badge success">booked</span>
          </div>
        `;
        })
        .join("")
    : '<p class="hint">На этот слот пока никто не записался.</p>';

  modal.hidden = false;
  document.body.classList.add("modal-open");
  return new Promise((resolve) => {
    let done = false;
    const close = () => {
      if (done) return;
      done = true;
      modal.hidden = true;
      document.body.classList.remove("modal-open");
      closeButtons.forEach((btn) => {
        btn.onclick = null;
      });
      closeBtn.onclick = null;
      resolve();
    };

    closeButtons.forEach((btn) => {
      btn.onclick = close;
    });
    closeBtn.onclick = close;
  });
}

function readFileAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(new Error("Не удалось прочитать файл"));
    reader.readAsDataURL(file);
  });
}

function cropAvatarDataUrl(dataUrl, outputSize = 512) {
  return new Promise((resolve) => {
    const image = new Image();
    image.onload = () => {
      try {
        const srcCanvas = document.createElement("canvas");
        srcCanvas.width = image.naturalWidth || image.width;
        srcCanvas.height = image.naturalHeight || image.height;
        const srcCtx = srcCanvas.getContext("2d", { willReadFrequently: true });
        if (!srcCtx || !srcCanvas.width || !srcCanvas.height) {
          resolve(dataUrl);
          return;
        }

        srcCtx.drawImage(image, 0, 0);
        const pixels = srcCtx.getImageData(0, 0, srcCanvas.width, srcCanvas.height).data;

        const width = srcCanvas.width;
        const height = srcCanvas.height;

        const fullBounds = { minX: 0, minY: 0, maxX: width - 1, maxY: height - 1 };

        const opaqueBounds = () => {
          let minX = width;
          let minY = height;
          let maxX = -1;
          let maxY = -1;
          for (let y = 0; y < height; y += 1) {
            for (let x = 0; x < width; x += 1) {
              const idx = (y * width + x) * 4;
              const alpha = pixels[idx + 3];
              if (alpha > 12) {
                if (x < minX) minX = x;
                if (y < minY) minY = y;
                if (x > maxX) maxX = x;
                if (y > maxY) maxY = y;
              }
            }
          }
          if (maxX < minX || maxY < minY) return null;
          return { minX, minY, maxX, maxY };
        };

        const uniformBorderBounds = () => {
          const px = (x, y) => {
            const idx = (y * width + x) * 4;
            return [pixels[idx], pixels[idx + 1], pixels[idx + 2], pixels[idx + 3]];
          };

          const corners = [px(0, 0), px(width - 1, 0), px(0, height - 1), px(width - 1, height - 1)];
          const avg = corners.reduce((acc, c) => [acc[0] + c[0], acc[1] + c[1], acc[2] + c[2]], [0, 0, 0]).map((v) => v / corners.length);
          const cornerSpread = corners.reduce(
            (max, c) => Math.max(max, Math.abs(c[0] - avg[0]) + Math.abs(c[1] - avg[1]) + Math.abs(c[2] - avg[2])),
            0
          );
          if (cornerSpread > 95) return null;
          const tolerance = 42;
          const isBorder = (idx) => {
            const alpha = pixels[idx + 3];
            if (alpha <= 12) return true;
            const diff = Math.abs(pixels[idx] - avg[0]) + Math.abs(pixels[idx + 1] - avg[1]) + Math.abs(pixels[idx + 2] - avg[2]);
            return diff <= tolerance;
          };

          let top = 0;
          let bottom = height - 1;
          let left = 0;
          let right = width - 1;

          while (top < height) {
            let hasContent = false;
            for (let x = 0; x < width; x += 1) {
              const idx = (top * width + x) * 4;
              if (!isBorder(idx)) {
                hasContent = true;
                break;
              }
            }
            if (hasContent) break;
            top += 1;
          }

          while (bottom >= 0) {
            let hasContent = false;
            for (let x = 0; x < width; x += 1) {
              const idx = (bottom * width + x) * 4;
              if (!isBorder(idx)) {
                hasContent = true;
                break;
              }
            }
            if (hasContent) break;
            bottom -= 1;
          }

          while (left < width) {
            let hasContent = false;
            for (let y = 0; y < height; y += 1) {
              const idx = (y * width + left) * 4;
              if (!isBorder(idx)) {
                hasContent = true;
                break;
              }
            }
            if (hasContent) break;
            left += 1;
          }

          while (right >= 0) {
            let hasContent = false;
            for (let y = 0; y < height; y += 1) {
              const idx = (y * width + right) * 4;
              if (!isBorder(idx)) {
                hasContent = true;
                break;
              }
            }
            if (hasContent) break;
            right -= 1;
          }

          if (right <= left || bottom <= top) return null;
          return { minX: left, minY: top, maxX: right, maxY: bottom };
        };

        const boundsArea = (b) => (b.maxX - b.minX + 1) * (b.maxY - b.minY + 1);
        const candidates = [opaqueBounds(), uniformBorderBounds()].filter(Boolean);
        let bestBounds = fullBounds;
        for (const candidate of candidates) {
          const area = boundsArea(candidate);
          if (area >= width * height * 0.09 && area < boundsArea(bestBounds)) {
            bestBounds = candidate;
          }
        }

        let minX = bestBounds.minX;
        let minY = bestBounds.minY;
        let maxX = bestBounds.maxX;
        let maxY = bestBounds.maxY;

        const cropWidthRaw = maxX - minX + 1;
        const cropHeightRaw = maxY - minY + 1;
        const pad = Math.max(2, Math.round(Math.max(cropWidthRaw, cropHeightRaw) * 0.06));
        minX = Math.max(0, minX - pad);
        minY = Math.max(0, minY - pad);
        maxX = Math.min(width - 1, maxX + pad);
        maxY = Math.min(height - 1, maxY + pad);

        const cropWidth = maxX - minX + 1;
        const cropHeight = maxY - minY + 1;
        const side = Math.max(cropWidth, cropHeight);
        const centerX = minX + cropWidth / 2;
        const centerY = minY + cropHeight / 2;

        let sx = Math.round(centerX - side / 2);
        let sy = Math.round(centerY - side / 2);
        if (sx < 0) sx = 0;
        if (sy < 0) sy = 0;
        if (sx + side > width) sx = Math.max(0, width - side);
        if (sy + side > height) sy = Math.max(0, height - side);
        const sSize = Math.min(side, width, height);

        const outCanvas = document.createElement("canvas");
        outCanvas.width = outputSize;
        outCanvas.height = outputSize;
        const outCtx = outCanvas.getContext("2d");
        if (!outCtx) {
          resolve(dataUrl);
          return;
        }
        outCtx.imageSmoothingEnabled = true;
        outCtx.imageSmoothingQuality = "high";
        outCtx.drawImage(srcCanvas, sx, sy, sSize, sSize, 0, 0, outputSize, outputSize);

        resolve(outCanvas.toDataURL("image/png"));
      } catch {
        resolve(dataUrl);
      }
    };
    image.onerror = () => resolve(dataUrl);
    image.src = dataUrl;
  });
}

function isMoscowAddress(value) {
  const text = String(value || "").toLowerCase();
  if (!text) return false;
  return ["москва", "мск", "moscow", "moskva"].some((part) => text.includes(part));
}

function isVideoMediaUrl(url) {
  const text = String(url || "").toLowerCase();
  return text.startsWith("data:video/") || /\.(mp4|mov|webm)(\?|$)/.test(text);
}

function renderReviewMediaGallery(items) {
  if (!Array.isArray(items) || !items.length) return "";
  const cells = items
    .slice(0, MAX_REVIEW_MEDIA_FILES)
    .map((src, index) => {
      const safeSrc = escapeHtml(src);
      const alt = `Медиа отзыва ${index + 1}`;
      if (isVideoMediaUrl(src)) {
        return `<a class="review-media-item" href="${safeSrc}" target="_blank" rel="noopener noreferrer"><video src="${safeSrc}" controls preload="metadata"></video></a>`;
      }
      return `<a class="review-media-item" href="${safeSrc}" target="_blank" rel="noopener noreferrer"><img src="${safeSrc}" alt="${alt}" loading="lazy" /></a>`;
    })
    .join("");
  return `<div class="review-media-grid">${cells}</div>`;
}

function toIsoFromLocalInput(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toISOString();
}

function toLocalInputFromIso(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const pad = (num) => String(num).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function toGoogleCalendarDate(isoValue) {
  const date = new Date(isoValue);
  if (Number.isNaN(date.getTime())) return "";
  return date.toISOString().replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z");
}

function googleCalendarUrlFromBooking(booking) {
  const start = toGoogleCalendarDate(booking.start_at);
  const end = toGoogleCalendarDate(booking.end_at);
  const params = new URLSearchParams({
    action: "TEMPLATE",
    text: booking.title || "МК-Маркет",
    dates: `${start}/${end}`,
    location: booking.location || "",
    details: `Бронь МК-Маркет. Количество участников: ${booking.guests || 1}`,
  });
  return `https://calendar.google.com/calendar/render?${params.toString()}`;
}

function parseDownloadFilename(disposition, fallbackName = "mk-market.ics") {
  const raw = String(disposition || "");
  const utf8Match = raw.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf8Match?.[1]) {
    try {
      return decodeURIComponent(utf8Match[1]);
    } catch {
      return utf8Match[1];
    }
  }
  const plainMatch = raw.match(/filename=\"?([^\";]+)\"?/i);
  if (plainMatch?.[1]) return plainMatch[1];
  return fallbackName;
}

async function downloadAuthorizedCalendar(path, fallbackName = "mk-market.ics") {
  const result = await api(path);
  const content = String(result?.text || "");
  const headers = result?.headers;
  const filename = parseDownloadFilename(headers?.get?.("Content-Disposition"), fallbackName);
  const blob = new Blob([content], { type: "text/calendar;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

function bindCalendarDownloadButtons(root = document) {
  root.querySelectorAll("[data-download-ics]").forEach((btn) => {
    if (btn.dataset.downloadBound === "1") return;
    btn.dataset.downloadBound = "1";
    btn.addEventListener("click", async () => {
      const path = btn.getAttribute("data-download-ics") || "";
      const fallbackName = btn.getAttribute("data-download-filename") || "mk-market.ics";
      const originalText = btn.textContent;
      btn.disabled = true;
      btn.textContent = "Скачиваем...";
      try {
        await downloadAuthorizedCalendar(path, fallbackName);
      } catch (e) {
        show(e.message);
      } finally {
        btn.disabled = false;
        btn.textContent = originalText;
      }
    });
  });
}

function setupMasterCabinetAutoRefresh(enabled) {
  if (masterCabinetRefreshTimer) {
    window.clearInterval(masterCabinetRefreshTimer);
    masterCabinetRefreshTimer = null;
  }
  if (!enabled) return;
  masterCabinetRefreshTimer = window.setInterval(() => {
    if (!qs("#cabinet-page")) return;
    if (!state.me || state.me.role !== "master") return;
    loadMyBookings().catch(() => {});
  }, 60_000);
}

function setAuthStatus(message, isError = false) {
  const el = qs("#auth-status");
  if (!el) return;
  el.textContent = message;
  el.style.color = isError ? "#b42318" : "#7d5c6c";
}

function toggleVerifyCard(show, email = "") {
  const card = qs("#verify-card");
  if (card) card.style.display = show ? "grid" : "none";
  const emailInput = qs("#verify-email");
  if (emailInput && email) emailInput.value = email;
  if (show && email) {
    state.pendingVerifyEmail = email;
    localStorage.setItem("pending_verify_email", email);
  }
  if (!show) {
    state.pendingVerifyEmail = "";
    localStorage.removeItem("pending_verify_email");
  }
}

function markActiveNav() {
  const path = window.location.pathname;
  const mapping = [
    { selector: "#nav-catalog-link", paths: ["/catalog.html"] },
    { selector: "#nav-my-page-link", paths: ["/master.html"] },
    { selector: "#nav-admin-link", paths: ["/new-workshop.html"] },
    { selector: "#nav-cabinet-avatar", paths: ["/cabinet.html"] },
  ];
  mapping.forEach((item) => {
    const el = qs(item.selector);
    if (!el) return;
    const active = item.paths.includes(path);
    el.classList.toggle("active", active);
  });
}

function validateEmail(email) {
  return /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email);
}

function parseRole(roleRaw) {
  const role = (roleRaw || "").toLowerCase();
  if (role.includes("мастер") || role.includes("studio") || role.includes("master")) {
    return "master";
  }
  return "user";
}

function getPrimaryRouteForRole(roleRaw) {
  return parseRole(roleRaw) === "master" ? "/new-workshop.html" : "/catalog.html";
}

function getPrimaryRouteForCurrentUser() {
  return getPrimaryRouteForRole(state.me?.role || "");
}

function authHeaders() {
  return state.token ? { Authorization: `Bearer ${state.token}` } : {};
}

async function api(path, options = {}) {
  const response = await fetch(`${apiBase}${path}`, {
    ...options,
    headers: {
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...(options.headers || {}),
      ...authHeaders(),
    },
  });

  if (response.headers.get("content-type")?.includes("text/calendar")) {
    const text = await response.text();
    return { text, headers: response.headers };
  }

  const json = await response.json().catch(() => ({}));
  if (!response.ok) {
    let detail = json.detail || "Request failed";
    if (Array.isArray(detail)) {
      detail = detail
        .map((item) => {
          if (typeof item === "string") return item;
          if (item && typeof item === "object") return item.msg || JSON.stringify(item);
          return String(item);
        })
        .join("; ");
    } else if (detail && typeof detail === "object") {
      detail = detail.msg || JSON.stringify(detail);
    }
    throw new Error(localizeErrorMessage(detail));
  }
  return json;
}

function updateNavUser() {
  const loginLink = qs("#nav-login-link");
  const cabinetAvatar = qs("#nav-cabinet-avatar");
  const catalogLink = qs("#nav-catalog-link");
  const myPageLink = qs("#nav-my-page-link");
  const adminLink = qs("#nav-admin-link");
  const logoutBtn = qs("#logout-btn");
  const logoLinks = document.querySelectorAll("a.logo");

  const isAuth = Boolean(state.me);
  const isMaster = isAuth && state.me.role === "master";
  logoLinks.forEach((link) => {
    link.href = isAuth ? "/catalog.html" : "/";
  });

  if (loginLink) loginLink.style.display = isAuth ? "none" : "inline-flex";
  if (cabinetAvatar) {
    cabinetAvatar.style.display = isAuth ? "inline-flex" : "none";
    if (isAuth) {
      const initials = (state.me.name || "ЛК")
        .split(/\s+/)
        .filter(Boolean)
        .slice(0, 2)
        .map((v) => v[0]?.toUpperCase() || "")
        .join("");
      cabinetAvatar.innerHTML = avatarBlock(state.me.avatar_url, initials || "ЛК");
      cabinetAvatar.href = "/cabinet.html";
    } else {
      cabinetAvatar.href = "/cabinet.html";
    }
  }
  if (catalogLink) catalogLink.style.display = isAuth ? "inline-flex" : "none";
  if (myPageLink) {
    myPageLink.style.display = isMaster ? "inline-flex" : "none";
    if (isMaster && state.me?.id) {
      myPageLink.href = `/master.html?id=${Number(state.me.id)}`;
    } else {
      myPageLink.href = "/master.html";
    }
  }
  if (adminLink) adminLink.style.display = isMaster ? "inline-flex" : "none";
  if (logoutBtn) logoutBtn.style.display = isAuth ? "inline-flex" : "none";
  applyImageFallbacks(document);
}

async function loadMe() {
  if (!state.token) {
    state.me = null;
    updateNavUser();
    return null;
  }
  try {
    state.me = await api("/me");
    updateNavUser();
    return state.me;
  } catch {
    state.token = "";
    state.me = null;
    localStorage.removeItem("token");
    updateNavUser();
    return null;
  }
}

async function login(email, password) {
  const data = await api("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
  state.token = data.token;
  localStorage.setItem("token", data.token);
  await loadMe();
  return data;
}

async function registerUser(email, password, passwordRepeat, role, name) {
  return api("/auth/register", {
    method: "POST",
    body: JSON.stringify({ email, password, password_repeat: passwordRepeat, role, name }),
  });
}

async function verifyEmail(email, code) {
  return api("/auth/verify-email", {
    method: "POST",
    body: JSON.stringify({ email, code }),
  });
}

async function requestLoginCode(email) {
  return api("/auth/request-login-code", {
    method: "POST",
    body: JSON.stringify({ email }),
  });
}

async function loginByCode(email, code) {
  const data = await api("/auth/login-by-code", {
    method: "POST",
    body: JSON.stringify({ email, code }),
  });
  state.token = data.token;
  localStorage.setItem("token", data.token);
  await loadMe();
  return data;
}

async function loadGoogleIntegration() {
  const status = qs("#google-status");
  const connectBtn = qs("#google-connect-btn");
  const syncBtn = qs("#google-sync-btn");
  const disconnectBtn = qs("#google-disconnect-btn");
  if (!status) return;
  if (!state.me) {
    status.textContent = "Войдите, чтобы подключить календарь.";
    return;
  }
  try {
    const data = await api("/integrations/google/status");
    if (data.connected) {
      status.textContent = `Google Calendar подключен (${data.calendar_id || "primary"})`;
      if (connectBtn) connectBtn.style.display = "none";
      if (syncBtn) syncBtn.style.display = "inline-flex";
      if (disconnectBtn) disconnectBtn.style.display = "inline-flex";
    } else {
      status.textContent = "Google Calendar не подключен";
      if (connectBtn) connectBtn.style.display = "inline-flex";
      if (syncBtn) syncBtn.style.display = "none";
      if (disconnectBtn) disconnectBtn.style.display = "none";
    }
  } catch (e) {
    status.textContent = `Ошибка интеграции: ${e.message}`;
  }
}

function logout() {
  state.token = "";
  state.me = null;
  localStorage.removeItem("token");
  updateNavUser();
  show("Вы вышли из аккаунта");
  if (window.location.pathname !== "/") {
    window.location.href = "/";
  }
}

function setupAuthControls() {
  const loginBtn = qs("#login-btn");
  const registerBtn = qs("#register-btn");
  const verifyBtn = qs("#verify-email-btn");
  const logoutBtn = qs("#logout-btn");
  const toggleLoginCodeBtn = qs("#toggle-login-code-btn");
  const requestLoginCodeBtn = qs("#request-login-code-btn");
  const loginByCodeBtn = qs("#login-by-code-btn");

  if (qs("#verify-card")) {
    if (state.pendingVerifyEmail) {
      toggleVerifyCard(true, state.pendingVerifyEmail);
    } else {
      toggleVerifyCard(false);
    }
  }

  if (toggleLoginCodeBtn) {
    toggleLoginCodeBtn.addEventListener("click", () => {
      const wrap = qs("#login-code-wrap");
      if (!wrap) return;
      const isHidden = wrap.style.display === "none";
      wrap.style.display = isHidden ? "grid" : "none";
      const loginEmail = (qs("#login-email")?.value || "").trim().toLowerCase();
      if (isHidden && loginEmail && qs("#login-code-email")) {
        qs("#login-code-email").value = loginEmail;
      }
    });
  }

  if (requestLoginCodeBtn) {
    requestLoginCodeBtn.addEventListener("click", async () => {
      const email = (qs("#login-code-email")?.value || qs("#login-email")?.value || "").trim().toLowerCase();
      if (!validateEmail(email)) {
        setAuthStatus("Введите корректную почту для входа по коду.", true);
        return;
      }
      try {
        await requestLoginCode(email);
        setAuthStatus("Если аккаунт существует, код отправлен на почту.");
      } catch (e) {
        setAuthStatus(e.message, true);
      }
    });
  }

  if (loginByCodeBtn) {
    loginByCodeBtn.addEventListener("click", async () => {
      const email = (qs("#login-code-email")?.value || qs("#login-email")?.value || "").trim().toLowerCase();
      const code = (qs("#login-code")?.value || "").trim();
      if (!validateEmail(email)) {
        setAuthStatus("Введите корректную почту для входа по коду.", true);
        return;
      }
      if (!code) {
        setAuthStatus("Введите код из письма.", true);
        return;
      }
      try {
        await loginByCode(email, code);
        setAuthStatus("Вход по коду выполнен. Перенаправляю...");
        toggleVerifyCard(false);
        window.location.href = getPrimaryRouteForCurrentUser();
      } catch (e) {
        const msg = String(e.message || "");
        if (msg.toLowerCase().includes("email not verified")) {
          toggleVerifyCard(true, email);
          setAuthStatus("Сначала подтвердите почту кодом регистрации.", true);
          return;
        }
        setAuthStatus(e.message, true);
      }
    });
  }

  if (loginBtn) {
    loginBtn.addEventListener("click", async () => {
      const email = (qs("#login-email")?.value || "").trim().toLowerCase();
      const password = qs("#login-password")?.value || "";

      if (!validateEmail(email)) {
        setAuthStatus("Введите корректную почту для входа.", true);
        return;
      }
      if (!password) {
        setAuthStatus("Введите пароль для входа.", true);
        return;
      }

      try {
        await login(email, password);
        setAuthStatus("Вход выполнен. Перенаправляю...");
        toggleVerifyCard(false);
        window.location.href = getPrimaryRouteForCurrentUser();
      } catch (e) {
        const msg = String(e.message || "");
        if (msg.toLowerCase().includes("email not verified")) {
          toggleVerifyCard(true, email);
          setAuthStatus("Сначала подтвердите почту кодом из письма.", true);
          return;
        }
        setAuthStatus(e.message, true);
      }
    });
  }

  if (registerBtn) {
    registerBtn.addEventListener("click", async () => {
      const name = (qs("#register-name")?.value || "").trim();
      const email = (qs("#register-email")?.value || "").trim().toLowerCase();
      const password = qs("#register-password")?.value || "";
      const passwordRepeat = qs("#register-password-repeat")?.value || "";
      const roleValue = parseRole(qs("#register-role")?.value || "");

      if (!name) {
        setAuthStatus("Введите ФИО.", true);
        return;
      }
      if (!validateEmail(email)) {
        setAuthStatus("Введите корректную почту для регистрации.", true);
        return;
      }
      if (password.length < 6) {
        setAuthStatus("Пароль должен быть не короче 6 символов.", true);
        return;
      }
      if (!passwordRepeat) {
        setAuthStatus("Повтори пароль.", true);
        return;
      }
      if (password !== passwordRepeat) {
        setAuthStatus("Пароли не совпадают.", true);
        return;
      }

      try {
        await registerUser(email, password, passwordRepeat, roleValue, name);
        toggleVerifyCard(true, email);
        setAuthStatus("Регистрация успешна. На почту отправлен код подтверждения.");
      } catch (e) {
        setAuthStatus(e.message, true);
      }
    });
  }

  if (verifyBtn) {
    verifyBtn.addEventListener("click", async () => {
      const email = (qs("#verify-email")?.value || "").trim().toLowerCase();
      const code = (qs("#verify-code")?.value || "").trim();
      if (!validateEmail(email)) {
        setAuthStatus("Введите корректную почту для подтверждения.", true);
        return;
      }
      if (!code) {
        setAuthStatus("Введите код подтверждения.", true);
        return;
      }
      try {
        await verifyEmail(email, code);
        toggleVerifyCard(false);
        setAuthStatus("Почта подтверждена. Теперь можно войти.");
      } catch (e) {
        setAuthStatus(e.message, true);
      }
    });
  }

  if (logoutBtn) logoutBtn.addEventListener("click", logout);
}

async function resolveSearchTarget(query) {
  const cleaned = query.trim();
  if (!cleaned) return { target: "/catalog.html" };
  try {
    return await api(`/search/resolve?q=${encodeURIComponent(cleaned)}`);
  } catch {
    return { target: "/catalog.html" };
  }
}

async function runSearch(query, date, sort, workshopType = "") {
  const resolved = await resolveSearchTarget(query);
  const target = resolved.target || "/catalog.html";
  const params = new URLSearchParams();
  if (query.trim()) params.set("q", query.trim());
  if (date) params.set("date", date);
  if (sort) params.set("sort", sort);
  if (workshopType.trim()) params.set("workshop_type", workshopType.trim());
  if (target.startsWith("/master.html") && resolved.master_id) {
    window.location.href = `${target}?id=${encodeURIComponent(String(resolved.master_id))}`;
    return;
  }
  window.location.href = params.toString() ? `${target}?${params.toString()}` : target;
}

function setupSearchControls() {
  const heroBtn = qs("#hero-search-btn");
  const catalogBtn = qs("#catalog-search-btn");

  if (heroBtn) {
    heroBtn.addEventListener("click", async () => {
      await runSearch(qs("#hero-search")?.value || "", qs("#hero-date")?.value || "", qs("#hero-filter")?.value || "");
    });
  }

  if (catalogBtn) {
    catalogBtn.addEventListener("click", async () => {
      await runSearch(
        qs("#catalog-search")?.value || "",
        qs("#catalog-date")?.value || "",
        qs("#catalog-filter")?.value || "",
        qs("#catalog-type")?.value || ""
      );
    });
  }

  const bindEnter = (selector, handler) => {
    const input = qs(selector);
    if (!input) return;
    input.addEventListener("keydown", async (event) => {
      if (event.key !== "Enter") return;
      event.preventDefault();
      await handler();
    });
  };
  bindEnter("#hero-search", async () => runSearch(qs("#hero-search")?.value || "", qs("#hero-date")?.value || "", qs("#hero-filter")?.value || ""));
  bindEnter(
    "#catalog-search",
    async () =>
      runSearch(
        qs("#catalog-search")?.value || "",
        qs("#catalog-date")?.value || "",
        qs("#catalog-filter")?.value || "",
        qs("#catalog-type")?.value || ""
      )
  );

  const params = new URLSearchParams(window.location.search);
  const q = params.get("q") || "";
  const date = params.get("date") || "";
  const sort = params.get("sort") || "";
  const workshopType = params.get("workshop_type") || "";

  const heroInput = qs("#hero-search");
  const catalogInput = qs("#catalog-search");
  if (heroInput) heroInput.value = q;
  if (catalogInput) catalogInput.value = q;
  if (qs("#hero-date")) qs("#hero-date").value = date;
  if (qs("#catalog-date")) qs("#catalog-date").value = date;
  if (sort && qs("#hero-filter")) qs("#hero-filter").value = sort;
  if (sort && qs("#catalog-filter")) qs("#catalog-filter").value = sort;
  if (qs("#catalog-type")) qs("#catalog-type").value = workshopType;
}

async function initCatalogPage() {
  const list = qs("#catalog-list");
  if (!list) return;

  const params = new URLSearchParams(window.location.search);
  const q = params.get("q") || "";
  const date = params.get("date") || "";
  const sortParam = params.get("sort") || "";
  const workshopType = params.get("workshop_type") || "";
  const sort = sortParam === "По понижению цены" ? "price_desc" : sortParam || "price_asc";

  try {
    const apiParams = new URLSearchParams();
    if (q) apiParams.set("q", q);
    if (date) apiParams.set("date", date);
    if (sort) apiParams.set("sort", sort);
    if (workshopType) apiParams.set("workshop_type", workshopType);
    const rows = await api(`/catalog?${apiParams.toString()}`);

    list.innerHTML = rows
      .map((item) => {
        const types = workshopTypesList(item.workshop_types || item.workshop_types_label, item.workshop_type || "Творческий МК");
        const typesLabel = types.join(", ") || "Творческий МК";
        const hasMultipleTypes = types.length > 1;
        const priceValue = Number(hasMultipleTypes ? item.min_price ?? item.price : item.price ?? item.min_price) || 0;
        const seatsValue = Number(hasMultipleTypes ? item.min_capacity ?? item.capacity : item.capacity ?? item.min_capacity) || 0;
        const priceLabel = `${hasMultipleTypes ? "от " : ""}${priceValue} ₽`;
        const seatsLabel = `${hasMultipleTypes ? "от " : ""}${seatsValue} человек`;
        return `
        <article class="mk-card">
          <a class="mk-cover-link" href="/mk.html?id=${item.id}">
            ${imageBlock(item.image_url, "mk-photo", "МК")}
          </a>
          <div class="mk-info">
            <h3><a class="mk-title-link" href="/mk.html?id=${item.id}">${escapeHtml(item.title)}</a></h3>
            <p>${escapeHtml(item.location || "Локация уточняется")} · мастер: <a class="master-link" href="/master.html?id=${item.master_id}">${escapeHtml(
              item.master_name
            )}</a></p>
            <p>Виды МК: ${escapeHtml(typesLabel)}</p>
            <div class="mk-meta">
              <span>${escapeHtml(priceLabel)}</span>
              <span>${escapeHtml(seatsLabel)}</span>
            </div>
          </div>
        </article>
      `;
      })
      .join("");

    if (rows.length === 0) {
      list.innerHTML = '<div class="card"><p>Ничего не найдено. Попробуй другой запрос.</p></div>';
    }
    applyImageFallbacks(list);
  } catch (e) {
    list.innerHTML = `<div class="card"><p>Ошибка загрузки каталога: ${escapeHtml(e.message)}</p></div>`;
  }
}

async function resolveMasterId() {
  const params = new URLSearchParams(window.location.search);
  const id = Number(params.get("id") || 0);
  if (id > 0) return id;

  const q = params.get("q") || "";
  if (!q) return null;

  const rows = await api(`/catalog?q=${encodeURIComponent(q)}`);
  return rows.length ? rows[0].master_id : null;
}

async function initMasterPage() {
  const container = qs("#master-container");
  if (!container) return;

  const masterId = await resolveMasterId();
  if (!masterId) {
    const services = qs("#master-services");
    if (services) services.innerHTML = "<div class=\"card\"><p>Пока нет мастеров на платформе.</p></div>";
    return;
  }

  let data;
  try {
    data = await api(`/masters/${masterId}`);
  } catch {
    const services = qs("#master-services");
    if (services) services.innerHTML = "<div class=\"card\"><p>Мастер не найден.</p></div>";
    return;
  }

  const masterName = qs("#master-name");
  if (masterName) masterName.textContent = data.master.name;
  if (qs("#master-name-heading")) qs("#master-name-heading").textContent = data.master.name;
  if (qs("#master-phone")) qs("#master-phone").textContent = data.master.phone || "-";
  if (qs("#master-bio")) qs("#master-bio").textContent = data.master.bio || "-";
  const masterAddressText = String(data.master.address || "").trim();
  if (qs("#master-address")) qs("#master-address").textContent = masterAddressText || "Адрес не указан";
  if (qs("#master-rating")) qs("#master-rating").textContent = String(data.stats.rating || 0);
  if (qs("#master-reviews-count")) qs("#master-reviews-count").textContent = String(data.stats.reviews_count || 0);
  const masterAvatar = qs("#master-avatar");
  if (masterAvatar) {
    const initials = (data.master.name || "МК")
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((v) => v[0]?.toUpperCase() || "")
      .join("");
    masterAvatar.innerHTML = avatarBlock(data.master.avatar_url, initials || "МК");
  }
  const map = qs("#master-map");
  const mapCard = qs("#master-map-card");
  const mapHint = qs("#master-map-hint");
  const showMoscowMap = isMoscowAddress(masterAddressText);
  if (map) {
    if (showMoscowMap) {
      const query = encodeURIComponent(masterAddressText);
      map.src = `https://www.google.com/maps?q=${query}&output=embed`;
      map.style.display = "block";
      if (mapHint) {
        mapHint.textContent = "";
        mapHint.style.display = "none";
      }
      if (mapCard) mapCard.style.display = "grid";
    } else {
      map.removeAttribute("src");
      map.style.display = "none";
      if (mapHint) {
        mapHint.textContent = "Карта показывается только для адресов в Москве.";
        mapHint.style.display = "block";
      }
      if (mapCard && !masterAddressText) mapCard.style.display = "none";
    }
  }

  const services = qs("#master-services");
  if (services) {
    services.innerHTML = data.workshops
      .map((w) => {
        const typesLabel = workshopTypesLabel(w.workshop_types || w.workshop_types_label, w.workshop_type || "Творческий МК");
        return `
        <article class="service">
          <div>
            <h3>${escapeHtml(w.title)}</h3>
            <p>${Number(w.duration_min || 0)} минут</p>
            <p>Виды МК: ${escapeHtml(typesLabel)}</p>
          </div>
          <div class="service-meta">
            <span>от ${Number(w.min_price || w.price || 0)} ₽</span>
            <a class="button" href="/mk.html?id=${w.id}">Записаться</a>
          </div>
        </article>
      `;
      })
      .join("");
  }

  const reviews = qs("#reviews-list");
  if (reviews) {
    reviews.innerHTML = data.reviews
      .map((r) => {
        const isOwnReview = state.me && Number(state.me.id || 0) === Number(r.user_id || 0);
        const canReply = state.me && state.me.role === "master" && Number(state.me.id || 0) === Number(masterId || 0);
        return `
          <article id="review-${Number(r.id || 0)}" class="review" data-review-id="${Number(r.id || 0)}">
            <div class="review-head">
              <div class="review-avatar">${avatarBlock(r.user_avatar, (r.user_name || "U").slice(0, 2).toUpperCase())}</div>
              <div>
                <strong>${escapeHtml(r.user_name)}</strong>
                <span>${"★".repeat(r.rating)}${"☆".repeat(5 - r.rating)}</span>
              </div>
            </div>
            <p>${escapeHtml(r.text)}</p>
            ${renderReviewMediaGallery(r.media)}
            ${r.master_reply ? `<div class="review-reply">Ответ мастера: ${escapeHtml(r.master_reply)}</div>` : ""}
            ${canReply ? `<div class="inline"><input id="reply-${r.id}" type="text" placeholder="Ответ мастера" value="${escapeHtml(r.master_reply || "")}" /><button class="button" data-reply-id="${r.id}">${r.master_reply ? "Обновить ответ" : "Ответить"}</button></div>` : ""}
            ${isOwnReview ? `<div class="inline"><button class="button ghost" data-edit-review-id="${r.id}">Изменить отзыв</button></div>` : ""}
          </article>
        `;
      })
      .join("");

    reviews.querySelectorAll("button[data-reply-id]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const id = Number(btn.getAttribute("data-reply-id"));
        const reply = qs(`#reply-${id}`)?.value || "";
        try {
          await api(`/reviews/${id}/reply`, { method: "POST", body: JSON.stringify({ reply }) });
          show("Ответ сохранен");
          initMasterPage();
        } catch (e) {
          show(e.message);
        }
      });
    });

    reviews.querySelectorAll("button[data-edit-review-id]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const id = Number(btn.getAttribute("data-edit-review-id"));
        const current = data.reviews.find((item) => Number(item.id || 0) === id);
        if (!current) return;
        const payload = await openReviewEditModal(current);
        if (!payload) return;

        try {
          await api(`/reviews/${id}`, {
            method: "PUT",
            body: JSON.stringify(payload),
          });
          show("Отзыв обновлен");
          initMasterPage();
        } catch (e) {
          show(e.message);
        }
      });
    });
    applyImageFallbacks(reviews);

    const reviewIdFromUrl = Number(new URLSearchParams(window.location.search).get("review_id") || 0);
    if (reviewIdFromUrl > 0) {
      const target = reviews.querySelector(`[data-review-id="${reviewIdFromUrl}"]`);
      if (target) {
        target.classList.add("review-target");
        target.scrollIntoView({ behavior: "smooth", block: "center" });
        setTimeout(() => target.classList.remove("review-target"), 2200);
      }
    }
  }

  const addReviewBtn = qs("#add-review-btn");
  const reviewFormCard = qs("#review-form-card");
  const reviewFormHint = qs("#review-form-hint");
  const reviewRatingInput = qs("#review-rating");
  const reviewTextInput = qs("#review-text");
  const reviewMediaInput = qs("#review-media-files");
  const reviewMediaInfo = qs("#review-media-info");
  const reviewPolicy = data.review_policy || {};
  const canAddReview = Boolean(reviewPolicy.can_add);
  const reviewPolicyCode = String(reviewPolicy.code || "");
  const reviewReason = String(reviewPolicy.reason || "Оставить отзыв можно только после посещения мастер-класса.");
  const hideReviewForm = reviewPolicyCode === "self review forbidden";

  if (reviewFormCard) reviewFormCard.style.display = hideReviewForm ? "none" : "grid";
  if (hideReviewForm) return;
  if (reviewFormHint) reviewFormHint.textContent = reviewReason;
  if (reviewRatingInput) reviewRatingInput.disabled = !canAddReview;
  if (reviewTextInput) reviewTextInput.disabled = !canAddReview;
  if (reviewMediaInput) reviewMediaInput.disabled = !canAddReview;
  if (addReviewBtn) addReviewBtn.disabled = !canAddReview;
  if (reviewMediaInfo && !state.reviewMediaDataUrls.length) {
    reviewMediaInfo.textContent = "Фото/видео не выбраны (до 3 файлов)";
  }
  if (reviewMediaInput) {
    reviewMediaInput.onchange = async (event) => {
      if (!canAddReview) return;
      const selected = Array.from(event.target.files || []);
      if (!selected.length) return;

      const parsed = await collectReviewMediaFromFiles(selected);
      if (!parsed.ok) {
        reviewMediaInput.value = "";
        if (reviewMediaInfo) reviewMediaInfo.textContent = parsed.error;
        return;
      }

      const merged = [...state.reviewMediaDataUrls, ...parsed.media];
      if (merged.length > MAX_REVIEW_MEDIA_FILES) {
        reviewMediaInput.value = "";
        if (reviewMediaInfo) reviewMediaInfo.textContent = "Можно прикрепить не более 3 фото/видео";
        return;
      }
      state.reviewMediaDataUrls = merged;
      if (reviewMediaInfo) reviewMediaInfo.textContent = `Файлов выбрано: ${state.reviewMediaDataUrls.length} / ${MAX_REVIEW_MEDIA_FILES}`;
      reviewMediaInput.value = "";
    };
  }

  if (addReviewBtn) {
    if (!canAddReview) {
      addReviewBtn.onclick = null;
      return;
    }
    addReviewBtn.onclick = async () => {
      const rating = Number(reviewRatingInput?.value || 5);
      const text = reviewTextInput?.value || "";
      try {
        await api("/reviews", {
          method: "POST",
          body: JSON.stringify({
            master_id: masterId,
            rating,
            text,
            media: state.reviewMediaDataUrls,
          }),
        });
        show("Отзыв добавлен");
        if (reviewTextInput) reviewTextInput.value = "";
        state.reviewMediaDataUrls = [];
        if (reviewMediaInput) reviewMediaInput.value = "";
        if (reviewMediaInfo) reviewMediaInfo.textContent = "Фото/видео не выбраны (до 3 файлов)";
        initMasterPage();
      } catch (e) {
        show(e.message);
      }
    };
  }
}

async function initWorkshopPage() {
  const container = qs("#workshop-container");
  if (!container) return;

  const workshopId = Number(new URLSearchParams(window.location.search).get("id") || 0);
  if (!workshopId) {
    qs("#slots-list").innerHTML = "<div class=\"card\"><p>Выбери мастер-класс в каталоге.</p></div>";
    return;
  }

  let data;
  try {
    data = await api(`/workshops/${workshopId}`);
  } catch {
    qs("#slots-list").innerHTML = "<div class=\"card\"><p>Мастер-класс не найден.</p></div>";
    return;
  }

  qs("#workshop-title").textContent = data.workshop.title;
  qs("#workshop-desc").textContent = data.workshop.description || "Описание скоро будет";
  if (qs("#workshop-type")) qs("#workshop-type").textContent = normalizeWorkshopType(data.workshop.workshop_type || "");
  qs("#workshop-location").textContent = data.workshop.location || "-";
  qs("#workshop-duration").textContent = `${data.workshop.duration_min} минут`;
  const workshopMasterLink = qs("#workshop-master-link");
  if (workshopMasterLink) {
    workshopMasterLink.textContent = data.workshop.master_name || "Мастер";
    workshopMasterLink.href = `/master.html?id=${Number(data.workshop.master_id || 0)}`;
  }
  const workshopPhoto = qs("#workshop-photo");
  if (workshopPhoto) {
    workshopPhoto.innerHTML = imageBlock(data.workshop.image_url, "mk-photo large", "Фото");
    applyImageFallbacks(workshopPhoto);
  }

  const guestsSelect = qs("#guests");
  if (guestsSelect) {
    const maxGuests = Math.max(1, Math.min(Number(data.workshop.capacity || 1), 10));
    guestsSelect.innerHTML = Array.from({ length: maxGuests }, (_, index) => `<option>${index + 1}</option>`).join("");
  }

  const slots = qs("#slots-list");
  if (!data.slots.length) {
    slots.innerHTML = '<div class="card"><p>Пока нет доступных слотов. Попросите мастера добавить расписание.</p></div>';
  } else {
    const nowMs = Date.now();
    const bookingWindowMs = 24 * 60 * 60 * 1000;
    slots.innerHTML = data.slots
      .map((slot) => {
        const startAtMs = new Date(slot.start_at).getTime();
        const isWithin24h = Number.isFinite(startAtMs) && startAtMs - nowMs < bookingWindowMs;
        const isFull = slot.free_seats <= 0;
        const myBookingStatus = String(slot.my_booking_status || "").toLowerCase();
        const isAlreadyBooked = myBookingStatus === "booked";
        const isAlreadyQueued = myBookingStatus === "queue";
        const buttonLabel = isWithin24h
          ? "Бронирование закрыто"
          : isAlreadyBooked
          ? "Вы уже записаны на данный МК"
          : isAlreadyQueued
          ? "Вы уже в очереди"
          : isFull
          ? "Встать в очередь"
          : "Записаться";
        const slotPrice = Number(slot.price || data.workshop.price || 0);
        const slotType = normalizeWorkshopType(slot.workshop_type || data.workshop.workshop_type || "");
        const isBlocked = isWithin24h || isAlreadyBooked || isAlreadyQueued;
        return `
        <div class="slot ${isFull ? "full" : ""}">
          <div>
            <strong>${new Date(slot.start_at).toLocaleString("ru-RU")}</strong>
            <span>Вид МК: ${escapeHtml(slotType)} · Свободно: ${slot.free_seats} · Цена: ${slotPrice} ₽${isWithin24h ? " · доступно только за 24 часа" : ""}</span>
          </div>
          <button class="button ${isBlocked ? "" : "primary"}" ${isBlocked ? "disabled" : `data-slot-id="${slot.id}"`}>
            ${buttonLabel}
          </button>
        </div>
        `;
      })
      .join("");
  }

  slots.querySelectorAll("button[data-slot-id]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const slotId = Number(btn.getAttribute("data-slot-id"));
      const guests = Number(qs("#guests")?.value || 1);
      try {
        const result = await api(`/workshops/${workshopId}/book`, {
          method: "POST",
          body: JSON.stringify({ slot_id: slotId, guests }),
        });
        if (result.status === "booked") {
          const links = await api(`/bookings/${result.booking_id}/calendar-links`);
          const wrap = qs("#booking-result");
          if (wrap) {
            wrap.innerHTML = `
              <button type="button" class="button" data-download-ics="${escapeHtml(links.apple_ics_url)}" data-download-filename="booking-${Number(result.booking_id || 0)}.ics">Apple Calendar</button>
              <a class="button" href="${links.google_url}" target="_blank" rel="noopener noreferrer">Google Calendar</a>
            `;
            bindCalendarDownloadButtons(wrap);
          }
        }
        show(result.message === "Booked" ? "Бронь подтверждена" : "Добавлены в очередь");
        initWorkshopPage();
      } catch (e) {
        show(e.message);
      }
    });
  });
}

async function loadMyBookings() {
  const list = qs("#my-bookings-list");
  if (!list || !state.me) return;

  if (state.me.role === "master") {
    const rows = await api("/me/master-upcoming-slots");
    if (!rows.length) {
      list.innerHTML = '<p class="hint">Ближайших мастер-классов на 24 часа нет.</p>';
      return;
    }
    list.innerHTML = rows
      .map((slot) => {
        const slotStart = new Date(slot.start_at).toLocaleString("ru-RU");
        const slotType = normalizeWorkshopType(slot.workshop_type || "");
        const bookedSeats = Number(slot.booked_seats || 0);
        const freeSeats = Number(slot.free_seats || 0);
        const totalSeats = Number(slot.total_seats || 0);
        const bookedRecords = Number(slot.booked_records || 0);
        const slotPrice = Number(slot.price || 0);
        return `
          <div class="booking-item master-slot-item">
            <div class="booking-main">
              <strong>${escapeHtml(slot.workshop_title || "Мастер-класс")}</strong>
              <span>${slotStart} · ${escapeHtml(slotType)} · ${slotPrice} ₽ · мест ${totalSeats} (занято ${bookedSeats}, свободно ${freeSeats}) · записей ${bookedRecords}</span>
            </div>
            <div class="inline booking-actions">
              <button type="button" class="button" data-download-ics="/api/admin/slots/${Number(slot.id || 0)}/calendar.ics" data-download-filename="master-slot-${Number(slot.id || 0)}.ics">Apple Calendar</button>
              <a
                class="button"
                href="${googleCalendarUrlFromBooking({
                  title: slot.workshop_title || "МК-Маркет",
                  start_at: slot.start_at,
                  end_at: slot.end_at,
                  location: slot.workshop_location || "",
                  guests: Math.max(1, bookedSeats),
                })}"
                target="_blank"
                rel="noopener noreferrer"
              >Google Calendar</a>
            </div>
          </div>
        `;
      })
      .join("");
    bindCalendarDownloadButtons(list);
    return;
  }

  const rows = await api("/me/bookings");
  const rowById = new Map(rows.map((item) => [Number(item.id), item]));

  if (!rows.length) {
    list.innerHTML = '<p class="hint">Пока нет записей.</p>';
    return;
  }

  list.innerHTML = rows
    .map(
      (b) => {
        const status = String(b.status || "");
        const canManageBooking = status === "booked" || status === "queue";
        return `
      <div class="booking-item">
        <div>
          <strong>${escapeHtml(b.title)}</strong>
          <span>${new Date(b.start_at).toLocaleString("ru-RU")} · ${Number(b.guests || 0)} гостей · ${escapeHtml(b.status)}</span>
        </div>
        <div class="booking-actions">
          ${
            status === "booked"
              ? `<button type="button" class="button booking-action-calendar" data-download-ics="/api/bookings/${b.id}/calendar.ics" data-download-filename="booking-${Number(b.id || 0)}.ics">Apple Calendar</button>
                 <a class="button booking-action-calendar" href="${googleCalendarUrlFromBooking(b)}" target="_blank" rel="noopener noreferrer">Google Calendar</a>`
              : ""
          }
          ${canManageBooking ? `<button class="button ghost booking-action-wide" data-move-id="${b.id}">Перенести</button>` : ""}
          ${canManageBooking ? `<button class="button ghost booking-action-wide" data-cancel-id="${b.id}">Отменить бронь</button>` : ""}
        </div>
      </div>
    `
      }
    )
    .join("");

  bindCalendarDownloadButtons(list);

  list.querySelectorAll("button[data-cancel-id]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const id = Number(btn.getAttribute("data-cancel-id"));
      try {
        await api(`/bookings/${id}/cancel`, { method: "POST" });
        show("Бронь отменена");
        loadMyBookings();
      } catch (e) {
        show(e.message);
      }
    });
  });

  list.querySelectorAll("button[data-move-id]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const id = Number(btn.getAttribute("data-move-id"));
      const booking = rowById.get(id) || {};
      try {
        const optionsPayload = await api(`/bookings/${id}/reschedule-options`);
        const movePayload = await openBookingMoveModal(booking, optionsPayload.options || []);
        if (!movePayload) return;
        await api(`/bookings/${id}/reschedule`, {
          method: "POST",
          body: JSON.stringify(movePayload),
        });
        show("Запись перенесена");
        await loadMyBookings();
      } catch (e) {
        show(e.message);
      }
    });
  });
}

async function loadMyReviews() {
  const list = qs("#my-reviews-list");
  if (!list || !state.me) return;

  const isMaster = state.me.role === "master";
  const rows = await api(isMaster ? "/me/reviews/received" : "/me/reviews");
  if (!rows.length) {
    list.innerHTML = `<p class="hint">${isMaster ? "Пока нет отзывов о вас." : "Пока нет отзывов."}</p>`;
    return;
  }

  if (isMaster) {
    list.innerHTML = rows
      .map((r) => {
        const rawRating = Number(r.rating || 0);
        const ratingVal = Number.isFinite(rawRating) ? Math.min(5, Math.max(1, Math.round(rawRating))) : 5;
        const stars = `${"★".repeat(ratingVal)}${"☆".repeat(5 - ratingVal)}`;
        const dateLabel = new Date(r.updated_at || r.created_at || "").toLocaleString("ru-RU");
        const replyValue = escapeHtml(r.master_reply || "");
        return `
        <div class="booking-item my-review-item">
          <div>
            <strong>${escapeHtml(r.user_name || "Пользователь")} · ${stars}</strong>
            <span>${escapeHtml(dateLabel)}</span>
            <p>${escapeHtml(r.text || "")}</p>
            ${renderReviewMediaGallery(r.media)}
            ${r.master_reply ? `<div class="review-reply">Ваш ответ: ${escapeHtml(r.master_reply)}</div>` : ""}
            <div class="inline my-review-actions">
              <input id="cabinet-reply-${Number(r.id || 0)}" type="text" placeholder="Ответ мастера" value="${replyValue}" />
              <button class="button ghost" data-my-review-reply-id="${Number(r.id || 0)}">${r.master_reply ? "Обновить ответ" : "Ответить"}</button>
              <a class="button" href="/master.html?id=${Number(r.master_id || state.me.id || 0)}&review_id=${Number(r.id || 0)}">К отзыву</a>
            </div>
          </div>
        </div>
      `;
      })
      .join("");

    list.querySelectorAll("button[data-my-review-reply-id]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const id = Number(btn.getAttribute("data-my-review-reply-id"));
        const reply = (qs(`#cabinet-reply-${id}`)?.value || "").trim();
        if (!reply) {
          show("Введите ответ на отзыв.");
          return;
        }
        try {
          await api(`/reviews/${id}/reply`, {
            method: "POST",
            body: JSON.stringify({ reply }),
          });
          show("Ответ сохранен");
          await loadMyReviews();
        } catch (e) {
          show(e.message);
        }
      });
    });
  } else {
    list.innerHTML = rows
      .map((r) => {
        const rawRating = Number(r.rating || 0);
        const ratingVal = Number.isFinite(rawRating) ? Math.min(5, Math.max(1, Math.round(rawRating))) : 5;
        const stars = `${"★".repeat(ratingVal)}${"☆".repeat(5 - ratingVal)}`;
        const dateLabel = new Date(r.updated_at || r.created_at || "").toLocaleString("ru-RU");
        return `
        <div class="booking-item my-review-item">
          <div>
            <strong><a class="master-link" href="/master.html?id=${Number(r.master_id || 0)}">${escapeHtml(r.master_name || "Мастер")}</a> · ${stars}</strong>
            <span>${escapeHtml(dateLabel)}</span>
            <p>${escapeHtml(r.text || "")}</p>
            ${renderReviewMediaGallery(r.media)}
            ${r.master_reply ? `<div class="review-reply">Ответ мастера: ${escapeHtml(r.master_reply)}</div>` : ""}
            <div class="inline my-review-actions">
              <button class="button ghost" data-my-review-edit-id="${Number(r.id || 0)}">Изменить</button>
              <a class="button" href="/master.html?id=${Number(r.master_id || 0)}&review_id=${Number(r.id || 0)}">К отзыву</a>
            </div>
          </div>
        </div>
      `;
      })
      .join("");

    list.querySelectorAll("button[data-my-review-edit-id]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const id = Number(btn.getAttribute("data-my-review-edit-id"));
        const current = rows.find((item) => Number(item.id || 0) === id);
        if (!current) return;
        const payload = await openReviewEditModal(current);
        if (!payload) return;
        try {
          await api(`/reviews/${id}`, {
            method: "PUT",
            body: JSON.stringify(payload),
          });
          show("Отзыв обновлен");
          await loadMyReviews();
        } catch (e) {
          show(e.message);
        }
      });
    });
  }

  applyImageFallbacks(list);
}

async function loadAdminData() {
  const adminWrap = qs("#admin-wrap");
  if (!adminWrap) return;
  if (!state.me || state.me.role !== "master") {
    adminWrap.innerHTML = '<p class="hint">Админка доступна только для мастера/студии.</p>';
    return;
  }

  const workshops = await api("/admin/workshops");
  const slotsData = await api("/admin/slots");
  const queue = await api("/admin/queue");
  const queueCountByWorkshop = queue.reduce((acc, item) => {
    const workshopId = Number(item.workshop_id || 0);
    if (!workshopId) return acc;
    acc[workshopId] = (acc[workshopId] || 0) + 1;
    return acc;
  }, {});

  const workshopList = qs("#admin-workshops");
  if (workshopList) {
    workshopList.innerHTML = workshops
      .map((w) => {
        const queueCount = Number(w.queue_count ?? queueCountByWorkshop[w.id] ?? 0);
        return `
        <div class="queue-item">
          <div class="workshop-admin-meta">
            <strong>${escapeHtml(w.title)}</strong>
            <span>${Number(w.duration_min || 0)} мин · параметры типа/цены/мест редактируются в слотах</span>
          </div>
          <div class="inline">
            <span class="badge">ID ${w.id}</span>
            <span class="badge ${queueCount > 0 ? "queue-badge" : ""}">Очередь: ${queueCount}</span>
            <button class="button" data-edit-workshop-id="${w.id}">Изменить</button>
            <button class="button danger" data-delete-workshop-id="${w.id}">Удалить</button>
          </div>
        </div>
      `
      })
      .join("");

    workshopList.querySelectorAll("button[data-delete-workshop-id]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const id = Number(btn.getAttribute("data-delete-workshop-id"));
        if (!window.confirm("Удалить мастер-класс? Слоты и записи тоже удалятся.")) return;
        try {
          await api(`/admin/workshops/${id}`, { method: "DELETE" });
          show("Мастер-класс удален");
          await loadAdminData();
        } catch (e) {
          show(e.message);
        }
      });
    });

    workshopList.querySelectorAll("button[data-edit-workshop-id]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const id = Number(btn.getAttribute("data-edit-workshop-id"));
        const current = workshops.find((w) => w.id === id);
        if (!current) return;
        const payload = await openWorkshopEditModal(current);
        if (!payload) return;

        try {
          await api(`/admin/workshops/${id}`, {
            method: "PUT",
            body: JSON.stringify(payload),
          });
          show("Мастер-класс обновлен");
          await loadAdminData();
        } catch (e) {
          show(e.message);
        }
      });
    });
  }

  const workshopSelect = qs("#slot-workshop-id");
  if (workshopSelect) {
    workshopSelect.innerHTML = workshops.map((w) => `<option value="${w.id}">${escapeHtml(w.title)}</option>`).join("");
  }

  const slotsList = qs("#admin-slots");
  if (slotsList) {
    slotsList.innerHTML = slotsData.length
      ? slotsData
          .map((slot) => {
            const isActive = String(slot.status || "open") === "open";
            return `
          <div class="queue-item">
            <div class="workshop-admin-meta">
              <strong>${escapeHtml(slot.workshop_title || "Мастер-класс")}</strong>
              <span>${new Date(slot.start_at).toLocaleString("ru-RU")} · ${escapeHtml(normalizeWorkshopType(slot.workshop_type || ""))} · ${Number(
              slot.price || 0
            )} ₽ · мест ${Number(slot.total_seats || 0)} (занято ${Number(slot.booked_seats || 0)}, свободно ${Number(slot.free_seats || 0)})</span>
            </div>
            <div class="inline">
              <span class="badge">Слот ID ${slot.id}</span>
              <span class="badge ${isActive ? "success" : ""}">${isActive ? "open" : escapeHtml(String(slot.status || "closed"))}</span>
              <button class="button ghost" data-slot-people-id="${slot.id}">Люди</button>
              <button class="button" data-edit-slot-id="${slot.id}">Изменить слот</button>
              <button class="button danger" data-delete-slot-id="${slot.id}">Удалить слот</button>
            </div>
          </div>
        `;
          })
          .join("")
      : '<p class="hint">Слотов пока нет.</p>';

    slotsList.querySelectorAll("button[data-edit-slot-id]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const slotId = Number(btn.getAttribute("data-edit-slot-id"));
        const current = slotsData.find((slot) => Number(slot.id || 0) === slotId);
        if (!current) return;
        const payload = await openSlotEditModal(current);
        if (!payload) return;
        try {
          await api(`/admin/slots/${slotId}`, {
            method: "PUT",
            body: JSON.stringify(payload),
          });
          show("Слот обновлен");
          await loadAdminData();
        } catch (e) {
          show(e.message);
        }
      });
    });

    slotsList.querySelectorAll("button[data-delete-slot-id]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const slotId = Number(btn.getAttribute("data-delete-slot-id"));
        if (!window.confirm("Удалить этот слот?")) return;
        try {
          await api(`/admin/slots/${slotId}`, { method: "DELETE" });
          show("Слот удален");
          await loadAdminData();
        } catch (e) {
          show(e.message);
        }
      });
    });

    slotsList.querySelectorAll("button[data-slot-people-id]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const slotId = Number(btn.getAttribute("data-slot-people-id"));
        const slot = slotsData.find((item) => Number(item.id || 0) === slotId);
        if (!slot) return;
        try {
          const payload = await api(`/admin/slots/${slotId}/people`);
          await openSlotPeopleModal(slot, payload.people || []);
        } catch (e) {
          show(e.message);
        }
      });
    });
  }

  const queueList = qs("#admin-queue");
  if (queueList) {
    queueList.innerHTML = queue.length
      ? queue
          .map(
            (q) => `
          <div class="queue-item">
            <div>
              <strong>${escapeHtml(q.user_name)}</strong>
              <span>${escapeHtml(q.title)} · ${new Date(q.start_at).toLocaleString("ru-RU")} · ${Number(q.guests || 0)} гостей</span>
            </div>
            <span class="badge">Очередь</span>
          </div>
        `
          )
          .join("")
      : '<p class="hint">Очередь пустая.</p>';
  }
}

async function initCabinetPage() {
  const cabinetWrap = qs("#cabinet-page");
  const adminPage = qs("#admin-page");
  if (!cabinetWrap && !adminPage) return;

  await loadMe();
  if (!state.me) {
    if (qs("#cabinet-auth-message")) qs("#cabinet-auth-message").textContent = "Сначала войдите на главной странице.";
    if (qs("#admin-auth-message")) qs("#admin-auth-message").textContent = "Сначала войдите на главной странице.";
    const adminWrap = qs("#admin-wrap");
    if (adminWrap) adminWrap.innerHTML = '<p class="hint">Требуется вход в аккаунт мастера.</p>';
    return;
  }

  if (adminPage && state.me.role !== "master") {
    if (qs("#admin-auth-message")) qs("#admin-auth-message").textContent = "";
    const adminWrap = qs("#admin-wrap");
    if (adminWrap) adminWrap.innerHTML = '<p class="hint">Только мастер может создавать новые мастер-классы.</p>';
    return;
  }

  if (cabinetWrap) {
    const isMaster = state.me.role === "master";
    const profileName = qs("#profile-name");
    const profileEmail = qs("#profile-email");
    const profilePhone = qs("#profile-phone");
    const profileBioField = qs("#profile-bio-field");
    const profileAddressField = qs("#profile-address-field");
    const profileBio = qs("#profile-bio");
    const profileAddress = qs("#profile-address");
    const profileAvatarFile = qs("#profile-avatar-file");
    const profileAvatarFileInfo = qs("#profile-avatar-file-info");

    if (profileBioField) profileBioField.style.display = isMaster ? "" : "none";
    if (profileAddressField) profileAddressField.style.display = isMaster ? "" : "none";
    const myBookingsTitle = qs("#my-bookings-title");
    const myBookingsHint = qs("#my-bookings-hint");
    if (myBookingsTitle) myBookingsTitle.textContent = isMaster ? "Мои мастер-классы" : "Мои записи";
    if (myBookingsHint) {
      myBookingsHint.textContent = isMaster
        ? "Показаны ближайшие слоты на 24 часа. Слот автоматически скрывается через 5 минут после старта."
        : "Отмена доступна минимум за 24 часа до старта МК.";
    }

    if (profileName) profileName.value = state.me.name || "";
    if (profileEmail) profileEmail.value = state.me.email || "";
    if (profilePhone) {
      profilePhone.value = normalizeRuPhone(state.me.phone || "");
      profilePhone.addEventListener("input", () => {
        profilePhone.value = normalizeRuPhone(profilePhone.value);
      });
    }
    if (profileBio) profileBio.value = state.me.bio || "";
    if (profileAddress) profileAddress.value = state.me.address || "";
    if (profileAvatarFileInfo) {
      profileAvatarFileInfo.textContent = state.me.avatar_url ? "Текущее фото установлено" : "Фото не выбрано";
    }
    if (profileAvatarFile) {
      profileAvatarFile.addEventListener("change", async (event) => {
        const file = event.target.files?.[0];
        if (!file) {
          state.newProfileAvatarDataUrl = "";
          if (profileAvatarFileInfo) profileAvatarFileInfo.textContent = state.me?.avatar_url ? "Текущее фото установлено" : "Фото не выбрано";
          return;
        }
        if (!file.type.startsWith("image/")) {
          state.newProfileAvatarDataUrl = "";
          profileAvatarFile.value = "";
          if (profileAvatarFileInfo) profileAvatarFileInfo.textContent = "Нужен файл изображения";
          return;
        }
        const dataUrl = await new Promise((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = () => resolve(String(reader.result || ""));
          reader.onerror = () => reject(new Error("Не удалось прочитать файл"));
          reader.readAsDataURL(file);
        }).catch((e) => {
          show(e.message);
          return "";
        });
        if (!dataUrl) return;
        state.newProfileAvatarDataUrl = await cropAvatarDataUrl(dataUrl);
        if (profileAvatarFileInfo) profileAvatarFileInfo.textContent = `Фото выбрано: ${file.name}`;
      });
    }
  }

  const saveBtn = qs("#save-profile-btn");
  if (saveBtn) {
    saveBtn.addEventListener("click", async () => {
      try {
        const phoneInput = qs("#profile-phone");
        const bioInput = qs("#profile-bio");
        const addressInput = qs("#profile-address");
        const avatarFileInput = qs("#profile-avatar-file");
        const avatarFileInfo = qs("#profile-avatar-file-info");
        const updated = await api("/me", {
          method: "PUT",
          body: JSON.stringify({
            name: qs("#profile-name").value,
            email: qs("#profile-email").value.trim().toLowerCase(),
            phone: normalizeRuPhone(phoneInput?.value || ""),
            avatar_url: state.newProfileAvatarDataUrl || state.me?.avatar_url || "",
            bio: bioInput ? bioInput.value : "",
            address: addressInput ? addressInput.value : "",
          }),
        });
        state.me = updated;
        state.newProfileAvatarDataUrl = "";
        if (avatarFileInput) avatarFileInput.value = "";
        if (avatarFileInfo) avatarFileInfo.textContent = state.me.avatar_url ? "Текущее фото установлено" : "Фото не выбрано";
        updateNavUser();
        if (updated.needs_email_verification) {
          state.pendingVerifyEmail = updated.email || "";
          localStorage.setItem("pending_verify_email", state.pendingVerifyEmail);
          show("Почта изменена. Подтвердите новый адрес кодом из письма.");
          window.location.href = "/#auth";
          return;
        }
        show("Профиль обновлен");
      } catch (e) {
        show(e.message);
      }
    });
  }

  const changePasswordBtn = qs("#change-password-btn");
  if (changePasswordBtn) {
    changePasswordBtn.addEventListener("click", async () => {
      try {
        await api("/me/password", {
          method: "POST",
          body: JSON.stringify({
            current_password: qs("#password-current").value,
            new_password: qs("#password-new").value,
            new_password_repeat: qs("#password-new-repeat").value,
          }),
        });
        qs("#password-current").value = "";
        qs("#password-new").value = "";
        qs("#password-new-repeat").value = "";
        show("Пароль изменен");
      } catch (e) {
        show(e.message);
      }
    });
  }

  if (cabinetWrap) {
    setupMasterCabinetAutoRefresh(state.me?.role === "master");
    await loadMyBookings();
    await loadMyReviews();
  } else {
    setupMasterCabinetAutoRefresh(false);
  }
  await loadAdminData();

  const createWorkshopBtn = qs("#create-workshop-btn");
  if (createWorkshopBtn) {
    createWorkshopBtn.addEventListener("click", async () => {
      try {
        await api("/admin/workshops", {
          method: "POST",
          body: JSON.stringify({
            title: qs("#new-workshop-title").value,
            description: qs("#new-workshop-description").value,
            location: qs("#new-workshop-location").value,
            duration_min: Number(qs("#new-workshop-duration").value || 0),
            image_url: state.newWorkshopImageDataUrl || "",
          }),
        });
        show("Мастер-класс создан");
        state.newWorkshopImageDataUrl = "";
        const workshopImageInput = qs("#new-workshop-image-file");
        if (workshopImageInput) workshopImageInput.value = "";
        const workshopImageInfo = qs("#new-workshop-image-info");
        if (workshopImageInfo) workshopImageInfo.textContent = "Фото не выбрано";
        loadAdminData();
      } catch (e) {
        show(e.message);
      }
    });
  }

  const workshopImageInput = qs("#new-workshop-image-file");
  if (workshopImageInput) {
    workshopImageInput.addEventListener("change", async (event) => {
      const file = event.target.files?.[0];
      const info = qs("#new-workshop-image-info");
      if (!file) {
        state.newWorkshopImageDataUrl = "";
        if (info) info.textContent = "Фото не выбрано";
        return;
      }
      if (!file.type.startsWith("image/")) {
        state.newWorkshopImageDataUrl = "";
        workshopImageInput.value = "";
        if (info) info.textContent = "Нужен файл изображения";
        return;
      }
      const dataUrl = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result || ""));
        reader.onerror = () => reject(new Error("Не удалось прочитать файл"));
        reader.readAsDataURL(file);
      }).catch((e) => {
        show(e.message);
        return "";
      });
      if (!dataUrl) return;
      state.newWorkshopImageDataUrl = dataUrl;
      if (info) info.textContent = `Фото выбрано: ${file.name}`;
    });
  }

  const slotTypeInput = qs("#slot-workshop-type");
  const slotSeatsInput = qs("#slot-seats");
  if (slotTypeInput && slotSeatsInput) {
    syncSlotSeatsByType(slotTypeInput, slotSeatsInput);
    slotTypeInput.addEventListener("change", () => syncSlotSeatsByType(slotTypeInput, slotSeatsInput));
  }

  const createSlotBtn = qs("#create-slot-btn");
  if (createSlotBtn) {
    createSlotBtn.addEventListener("click", async () => {
      try {
        const workshopId = Number(qs("#slot-workshop-id").value || 0);
        const workshopType = normalizeWorkshopType(slotTypeInput ? slotTypeInput.value : WORKSHOP_TYPE_OPTIONS[0]);
        const price = Number(qs("#slot-price").value || 0);
        const startAt = toIsoFromLocalInput(qs("#slot-start").value);
        let seats = Number(qs("#slot-seats").value || 0);
        if (workshopType !== "Групповой МК") {
          seats = capacityForWorkshopType(workshopType);
        }
        if (!startAt) {
          show("Выбери корректные дату и время начала слота");
          return;
        }
        if (!Number.isFinite(price) || price <= 0) {
          show("Укажи цену больше 0");
          return;
        }
        if (!Number.isFinite(seats) || seats <= 0) {
          show("Укажи количество человек в слоте больше 0");
          return;
        }
        await api(`/admin/workshops/${workshopId}/slots`, {
          method: "POST",
          body: JSON.stringify({
            start_at: startAt,
            total_seats: seats,
            workshop_type: workshopType,
            price,
          }),
        });
        show("Слот добавлен");
        loadAdminData();
      } catch (e) {
        show(e.message);
      }
    });
  }
}

(async function init() {
  markActiveNav();
  setupAuthControls();
  setupSearchControls();
  await loadMe();
  await initCatalogPage();
  await initMasterPage();
  await initWorkshopPage();
  await initCabinetPage();
})();
