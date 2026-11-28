/* clinic-face-ai — jQuery frontend.
   Upload -> POST /api/analyze (demo JSON for now) -> render Glow Score,
   metrics, zones and treatment cards. Doctor toggles build the plan live. */

$(function () {
  const INTENSITIES = ["خفیف", "ملایم", "محسوس"];
  // Marker positions (% of the photo box). Tuned for close-up front selfies:
  // the face fills most of the frame, so the lower markers sit higher than
  // before — jawline/chin used to land on the neck/shirt. Fixed % is still
  // approximate without face detection.
  const ZONE_POS = { 1: [50, 18], 2: [50, 34], 3: [70, 44], 4: [50, 48], 5: [62, 60], 6: [60, 70], 7: [50, 66], 8: [30, 50], 9: [50, 72], 10: [50, 78] };
  // Zone -> the treatment that belongs to it. The plan lists ALL 10 zones
  // (plus whole-face skin treatment), each with its own checkbox + intensity;
  // the model's suggestions only pre-check / pre-set the intensity.
  const ZONE_TREATMENT = {
    1: { id: "forehead-botox", name: "بوتاکس پیشانی" },
    2: { id: "frown-botox", name: "بوتاکس خط اخم" },
    3: { id: "eyes-botox", name: "بوتاکس دور چشم" },
    4: { id: "undereye-filler", name: "فیلر زیر چشم" },
    5: { id: "nasolabial-filler", name: "فیلر خط خنده" },
    6: { id: "marionette-filler", name: "فیلر خط غم" },
    7: { id: "lip-filler", name: "فیلر لب" },
    8: { id: "cheek-filler", name: "فیلر گونه" },
    9: { id: "jawline-filler", name: "فیلر خط فک" },
    10: { id: "chin-filler", name: "فیلر چانه" },
  };
  const SKIN_TREATMENT = { id: "skin-treatment", name: "درمان‌های جوانسازی پوست" };
  let analysis = null;
  let selectedZone = null;
  let previewLevel = "استاندارد"; // "ملایم" = each intensity one step gentler
  const plan = {}; // treatmentId -> { name, intensity }

  // Preview level toggle: ملایم shows the subtle end of the range first.
  $("#previewGentle").on("click", function () {
    previewLevel = "ملایم";
    $("#previewGentle").addClass("active");
    $("#previewStandard").removeClass("active");
  });
  $("#previewStandard").on("click", function () {
    previewLevel = "استاندارد";
    $("#previewStandard").addClass("active");
    $("#previewGentle").removeClass("active");
  });

  function showPhoto(src) {
    $("#photoPreview").attr("src", src).prop("hidden", false);
    $("#photoBox").addClass("has-photo");
    $("#photoPlaceholder").hide();
    $("#analyzeBtn").prop("disabled", false);
    $("#uploadHint").text("عکس آماده است — «شروع تحلیل» را بزنید.");
    // Fresh photo = no analysis yet: full-width photo, hide old results
    // and zone markers so the new photo starts clean.
    $(".page").removeClass("split");
    $("#resultCard, #zonesCard, #treatmentsCard, #afterCard, #planCard").prop("hidden", true);
    $("#zoneMarkers").empty();
    analysis = null;
    realAfter = false;
  }

  $("#photoInput").on("change", function () {
    const file = this.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (e) => showPhoto(e.target.result);
    reader.readAsDataURL(file);
  });

  // Sample photo: a soft placeholder portrait drawn on canvas, so the
  // demo works with no upload. Real photos come from the file input.
  $("#sampleBtn").on("click", function () {
    const c = document.createElement("canvas");
    c.width = 600; c.height = 600;
    const x = c.getContext("2d");
    const g = x.createLinearGradient(0, 0, 600, 600);
    g.addColorStop(0, "#ffe3ea"); g.addColorStop(1, "#c0bafb");
    x.fillStyle = g; x.fillRect(0, 0, 600, 600);
    x.fillStyle = "#f6c9a8";
    x.beginPath(); x.arc(300, 300, 150, 0, Math.PI * 2); x.fill();
    x.fillStyle = "#3a2a2a";
    x.beginPath(); x.arc(300, 210, 150, Math.PI, 0); x.fill();
    x.fillStyle = "#2b2135";
    x.beginPath(); x.arc(250, 290, 12, 0, Math.PI * 2); x.fill();
    x.beginPath(); x.arc(350, 290, 12, 0, Math.PI * 2); x.fill();
    x.strokeStyle = "#c26a7a"; x.lineWidth = 8;
    x.beginPath(); x.arc(300, 360, 45, 0.15 * Math.PI, 0.85 * Math.PI); x.stroke();
    showPhoto(c.toDataURL("image/png"));
  });

  // Phone selfies are several MB — shrink to max 1024px before upload so
  // the analysis does not crawl on a slow connection. Falls back to the
  // original file if anything goes wrong.
  function shrinkPhoto(file) {
    return new Promise((resolve) => {
      const reader = new FileReader();
      reader.onload = (e) => {
        const img = new Image();
        img.onload = () => {
          const scale = Math.min(1, 1024 / Math.max(img.width, img.height));
          if (scale === 1) { resolve(file); return; }
          const c = document.createElement("canvas");
          c.width = Math.round(img.width * scale);
          c.height = Math.round(img.height * scale);
          c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
          c.toBlob((b) => resolve(b || file), "image/jpeg", 0.85);
        };
        img.onerror = () => resolve(file);
        img.src = e.target.result;
      };
      reader.onerror = () => resolve(file);
      reader.readAsDataURL(file);
    });
  }

  $("#analyzeBtn").on("click", function () {
    const file = $("#photoInput")[0].files[0];
    $("#scanLine").prop("hidden", false);
    $("#analyzeBtn").prop("disabled", true).text("در حال تحلیل…");
    $("#uploadHint").text("در حال ارسال عکس و تحلیل…");
    const send = (blob, name) => {
      const form = new FormData();
      form.append("file", blob, name);
      $.ajax({
        url: "/api/analyze", method: "POST", data: form,
        processData: false, contentType: false, timeout: 120000,
        success: (data) => {
          // A gateway failure comes back as {"error": ...} with no scores.
          // Show the real error instead of rendering it as analysis —
          // otherwise the score counter runs forever (no target to stop at).
          if (data.error) {
            $("#uploadHint").text(data.error);
            return;
          }
          render(data);
        },
        error: (xhr, status) => $("#uploadHint").text(
          status === "timeout"
            ? "خیلی طول کشید — اینترنت یا درگاه کند است؛ دوباره امتحان کنید."
            : "تحلیل انجام نشد — دوباره امتحان کنید."
        ),
        complete: () => {
          $("#scanLine").prop("hidden", true);
          $("#analyzeBtn").prop("disabled", false).text("شروع تحلیل");
        },
      });
    };
    if (file) {
      shrinkPhoto(file).then((blob) => send(blob, "photo.jpg"));
    } else {
      // No upload: send the preview (sample drawing) as a real image file,
      // so the gateway analyzes it instead of falling back to demo data.
      const src = $("#photoPreview").attr("src");
      if (src) send(dataUrlToBlob(src), "photo.png");
      else send(new Blob(["demo"], { type: "text/plain" }), "demo.txt");
    }
  });

  let zoom = 1, panX = 0, panY = 0;
  let realAfter = false; // true once the image model returned a real after-photo

  function dataUrlToBlob(dataUrl) {
    const parts = dataUrl.split(",");
    const mime = parts[0].match(/:(.*?);/)[1];
    const bin = atob(parts[1]);
    const arr = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
    return new Blob([arr], { type: mime });
  }

  function selectedTreatments() {
    const list = [];
    $(".treatment").each(function () {
      if (!$(this).find(".doctor-check").is(":checked")) return;
      list.push({
        id: $(this).data("id"),
        intensity: $(this).find(".intensity button.active").text(),
      });
    });
    return list;
  }

  function updateAfter() {
    // Demo-only preview: a filter on the SAME photo, strength follows the
    // selected intensities. Skipped once the real after-photo is shown.
    const levels = { "خفیف": 1, "ملایم": 2, "محسوس": 3 };
    let total = 0, count = 0;
    $(".treatment").each(function () {
      if (!$(this).find(".doctor-check").is(":checked")) return;
      count += 1;
      total += levels[$(this).find(".intensity button.active").text()] || 2;
    });
    const strength = count === 0 ? 0 : total / count; // 0..3
    const blur = (strength * 0.35).toFixed(2);
    const bright = (1 + strength * 0.02).toFixed(2);
    if (!realAfter) {
      $("#afterImg").css(
        "filter",
        `brightness(${bright}) saturate(1.08) contrast(0.97) blur(${blur}px)`
      );
    }
    // The compare card is never hidden here anymore: it is shown right after
    // analysis with the filter preview, even with no treatment checked, so
    // the doctor always sees where "before / after" lives.
  }

  // Real after-photo: POST /api/simulate with the photo + doctor's plan.
  $("#simulateBtn").on("click", function () {
    const selected = selectedTreatments();
    if (selected.length === 0) {
      $("#simulateStatus").text("اول حداقل یک درمان را انتخاب کنید.");
      return;
    }
    const src = $("#photoPreview").attr("src");
    if (!src) return;
    const btn = $(this);
    btn.prop("disabled", true).text("در حال ساخت عکس بعد…");
    $("#simulateStatus").text("در حال ساخت عکس واقعی… چند ثانیه طول می‌کشد.");
    const sendSimulate = (blob, name) => {
      const form = new FormData();
      form.append("file", blob, name);
      form.append("treatments", JSON.stringify(selected));
      form.append("preview", previewLevel);
      $.ajax({
        url: "/api/simulate", method: "POST", data: form,
        processData: false, contentType: false, timeout: 180000,
        success: (data) => {
          if (data.error) {
            $("#simulateStatus").text(data.message || data.error);
            return;
          }
          realAfter = true;
          $("#afterImg").attr("src", data.image).css("filter", "none");
          $("#simulateStatus").text("عکس واقعی ساخته شد — " + (data.disclaimer || ""));
          setCompare(50);
          // Bring the result to the doctor: scroll the compare into view.
          $("#afterCard")[0].scrollIntoView({ behavior: "smooth", block: "start" });
        },
        error: (xhr, status) => $("#simulateStatus").text(
          status === "timeout"
            ? "ساخت عکس خیلی طول کشید — دوباره امتحان کنید."
            : "ساخت عکس انجام نشد — دوباره امتحان کنید."
        ),
        complete: () => btn.prop("disabled", false).text("ساخت عکس واقعی «بعد»"),
      });
    };
    const file = $("#photoInput")[0].files[0];
    if (file) shrinkPhoto(file).then((blob) => sendSimulate(blob, "photo.jpg"));
    else sendSimulate(dataUrlToBlob(src), "photo.png");
  });

  function applyZoom() {
    $("#zoomSlider").val(zoom);
    $("#zoomLabel").text(`زوم: ${zoom.toLocaleString("fa-IR")}×`);
    $("#compareBox").toggleClass("zoomed", zoom > 1);
    $("#compareBox img, #compareBox .before-wrap").css(
      "transform", `translate(${panX}px, ${panY}px) scale(${zoom})`
    );
  }

  // Before/after slider: value 100 = only "before" visible, 0 = only "after".
  // The compare box is dir="ltr" so the slider is never flipped by RTL.
  function setCompare(v) {
    const val = Math.max(0, Math.min(100, Number(v) || 0));
    $("#compareSlider").val(val);
    $("#beforeWrap").css("clip-path", `inset(0 ${100 - val}% 0 0)`);
  }
  $("#compareSlider").on("input", function () { setCompare(this.value); });
  $("#compareBeforeBtn").on("click", () => setCompare(100));
  $("#compareSplitBtn").on("click", () => setCompare(50));
  $("#compareAfterBtn").on("click", () => setCompare(0));
  $("#zoomIn").on("click", () => { zoom = Math.min(3, zoom + 0.5); applyZoom(); });
  $("#zoomOut").on("click", () => { zoom = Math.max(1, zoom - 0.5); if (zoom === 1) { panX = 0; panY = 0; } applyZoom(); });
  $("#zoomSlider").on("input", function () { zoom = Number(this.value); if (zoom === 1) { panX = 0; panY = 0; } applyZoom(); });
  $("#zoomReset").on("click", () => { zoom = 1; panX = 0; panY = 0; applyZoom(); });
  // Drag to pan while zoomed.
  let dragging = false, startX = 0, startY = 0;
  $("#compareBox").on("mousedown touchstart", function (e) {
    if (zoom <= 1) return;
    dragging = true;
    const p = e.originalEvent.touches ? e.originalEvent.touches[0] : e;
    startX = p.clientX - panX; startY = p.clientY - panY;
  });
  $(document).on("mousemove touchmove", function (e) {
    if (!dragging) return;
    const p = e.originalEvent.touches ? e.originalEvent.touches[0] : e;
    panX = p.clientX - startX; panY = p.clientY - startY;
    applyZoom();
  });
  $(document).on("mouseup touchend", () => { dragging = false; });

  function render(data) {
    analysis = data;
    realAfter = false;
    // Analysis arrived: split the page — photo right, text/doctor left.
    $(".page").addClass("split");
    // The badge used to always say "demo data" even for a real gateway
    // analysis — show the truth: green "real analysis" when demo is false.
    const badge = $("#analysisBadge");
    if (data.demo) {
      badge.removeClass("real-badge").text("داده‌ی نمایشی — تحلیل واقعی بعد از اتصال درگاه");
    } else {
      badge.addClass("real-badge").text("تحلیل واقعی — با درگاه هرموز");
    }
    // The compare card is shown right after analysis with the filter preview
    // as the "after" side — it is NOT gated on a successful real simulate
    // (that gate is why the doctor could not find the compare at all).
    $("#resultCard, #zonesCard, #treatmentsCard, #planCard, #afterCard").prop("hidden", false);
    $("#uploadHint").text("تحلیل انجام شد — نتیجه را ببینید.");
    const src = $("#photoPreview").attr("src");
    if (src) { $("#afterImg, #beforeImg").attr("src", src); $("#afterImg").css("filter", ""); }
    $("#simulateStatus").text("تا وقتی عکس واقعی ساخته نشده، پیش‌نمایش با فیلتر نمایشی است. هر عکس واقعی حدود ۰٫۰۳۴ دلار هزینه دارد.");
    setCompare(50);
    applyZoom();

    // Quality + agreement note: photo problems and run-to-run disagreement
    // are shown plainly instead of hidden behind the score.
    const notes = [];
    if (data.photo_quality && data.photo_quality.note) {
      notes.push(data.photo_quality.ok ? "کیفیت عکس: " + data.photo_quality.note
        : "⚠ کیفیت عکس: " + data.photo_quality.note);
    }
    if (data.agreement_note) notes.push("⚠ " + data.agreement_note);
    if (data.hydration_note) notes.push(data.hydration_note);
    if (notes.length) $("#qualityNote").prop("hidden", false).text(notes.join(" "));
    else $("#qualityNote").prop("hidden", true);

    // Overall clinical impression (the doctor's-eye first look).
    if (data.overall_impression) {
      $("#overallImpression").prop("hidden", false).text(data.overall_impression);
    } else {
      $("#overallImpression").prop("hidden", true);
    }

    // Glow Score ring, animated count. Clamp 0-100 so a bad value can
    // never send the counter running forever.
    let n = 0;
    const target = Math.max(0, Math.min(100, Number(data.glow_score) || 0));
    const ring = $("#glowRing");
    const timer = setInterval(() => {
      n += 2;
      if (n >= target) { n = target; clearInterval(timer); }
      $("#glowScore").text(n);
      ring.css("--p", n);
    }, 24);

    $("#metrics").empty();
    (data.metrics || []).forEach((m) => {
      const v = (m.value == null ? 0 : m.value);
      $("#metrics").append(
        `<div class="metric"><span>${m.label || ""}</span>` +
        `<span class="bar"><i style="width:${v}%"></i></span>` +
        `<b>${v}٪</b></div>`
      );
    });

    $("#zoneChips").empty(); $("#zoneMarkers").empty();
    (data.zones || []).forEach((z) => {
      $("#zoneChips").append(`<button class="chip" data-id="${z.id}" type="button">${z.name || ""}</button>`);
      const [left, top] = ZONE_POS[z.id] || [50, 50];
      $("#zoneMarkers").append(
        `<span class="zone-dot" data-id="${z.id}" style="left:${left}%; top:${top}%">${z.id}</span>`
      );
    });
    if ((data.zones || []).length) selectZone(data.zones[0].id);
    else $("#zoneNote").text("");

    buildTreatments(data);
    // What NOT to touch — the doctor's restraint, shown under the plan.
    if (data.do_not_touch && data.do_not_touch.length) {
      $("#doNotTouchList").empty();
      data.do_not_touch.forEach((item) => $("#doNotTouchList").append(`<li>${item || ""}</li>`));
      $("#doNotTouch").prop("hidden", false);
    } else {
      $("#doNotTouch").prop("hidden", true);
    }
    updatePlan();
  }

  // Plan = ALL 10 zones, each with its own checkbox + 3 intensities, plus
  // the whole-face skin treatment as an extra row. The model's suggestions
  // only pre-check the box, set the intensity and carry the priority badge;
  // the doctor can check any zone and the simulate uses the full selection.
  function buildTreatments(data) {
    const suggested = {};
    (data.treatments || []).forEach((t) => { suggested[t.id] = t; });
    const rows = [];
    (data.zones || []).forEach((z) => {
      const def = ZONE_TREATMENT[z.id];
      if (!def) return;
      const s = suggested[def.id];
      rows.push({
        zoneId: z.id, zoneName: z.name || "", zoneValue: z.value,
        id: def.id, name: def.name,
        priority: s ? (s.priority || null) : null,
        intensity: (s && INTENSITIES.includes(s.intensity)) ? s.intensity : "محسوس",
        checked: !!s,
      });
    });
    // Whole-face skin treatment: its own row, ordered by model priority.
    const skin = suggested[SKIN_TREATMENT.id];
    rows.push({
      zoneId: null, zoneName: "کل صورت", zoneValue: null,
      id: SKIN_TREATMENT.id, name: SKIN_TREATMENT.name,
      priority: skin ? (skin.priority || null) : null,
      intensity: (skin && INTENSITIES.includes(skin.intensity)) ? skin.intensity : "محسوس",
      checked: !!skin,
    });
    // Suggested first, in the model's priority order; the rest in zone order.
    rows.sort((a, b) => {
      const pa = a.priority == null ? 99 : a.priority;
      const pb = b.priority == null ? 99 : b.priority;
      if (pa !== pb) return pa - pb;
      const za = a.zoneId == null ? 99 : a.zoneId;
      const zb = b.zoneId == null ? 99 : b.zoneId;
      return za - zb;
    });
    $("#treatments").empty();
    rows.forEach((r) => {
      const buttons = INTENSITIES.map((label) =>
        `<button type="button" data-intensity="${label}" class="${label === r.intensity ? "active" : ""}">${label}</button>`
      ).join("");
      const badge = r.priority != null ? `<span class="priority-badge">اولویت ${r.priority}</span>` : "";
      const sub = r.zoneId != null
        ? `<div class="treatment-zone">ناحیه: ${r.zoneName}${r.zoneValue != null ? " — " + r.zoneValue + "٪" : ""}</div>`
        : `<div class="treatment-zone">ناحیه: کل صورت</div>`;
      $("#treatments").append(
        `<div class="treatment" data-id="${r.id}" data-zone="${r.zoneId == null ? "" : r.zoneId}" data-priority="${r.priority == null ? "" : r.priority}">
          <div class="treatment-head"><h3>${r.name}</h3>${badge}</div>
          ${sub}
          <div class="intensity">${buttons}</div>
          <label class="doctor-toggle"><input type="checkbox" class="doctor-check"${r.checked ? " checked" : ""}> انتخاب پزشک</label>
        </div>`
      );
    });
  }

  // Clicking a zone marker/chip selects that zone's plan row: check it,
  // scroll it into view and highlight it so the doctor sees the link.
  function focusPlanRow(zoneId) {
    const row = $(`.treatment[data-zone="${zoneId}"]`);
    if (!row.length) return;
    if (!row.find(".doctor-check").is(":checked")) {
      row.find(".doctor-check").prop("checked", true);
    }
    updatePlan();
    row[0].scrollIntoView({ behavior: "smooth", block: "center" });
    $(".treatment").removeClass("highlight");
    row.addClass("highlight");
    clearTimeout(window._planHighlightTimer);
    window._planHighlightTimer = setTimeout(() => row.removeClass("highlight"), 3000);
  }

  function selectZone(id) {
    selectedZone = id;
    $(".chip, .zone-dot").removeClass("active");
    $(`.chip[data-id="${id}"], .zone-dot[data-id="${id}"]`).addClass("active");
    const z = ((analysis && analysis.zones) || []).find((item) => item.id === id);
    if (!z) { $("#zoneNote").text(""); return; }
    const head = (z.name || "") + (z.value != null ? ": " + z.value + "٪" : "");
    $("#zoneNote").text(z.note ? (head ? head + " — " + z.note : z.note) : head);
  }

  $(document).on("click", ".chip, .zone-dot", function () {
    const id = Number($(this).data("id"));
    selectZone(id);
    focusPlanRow(id);
  });

  $(document).on("click", ".intensity button", function () {
    $(this).siblings().removeClass("active");
    $(this).addClass("active");
    updatePlan();
  });

  $(document).on("change", ".doctor-check", updatePlan);

  function updatePlan() {
    let count = 0;
    $("#planList").empty();
    $(".treatment").each(function () {
      const checked = $(this).find(".doctor-check").is(":checked");
      if (!checked) return;
      count += 1;
      const name = $(this).find("h3").text();
      const intensity = $(this).find(".intensity button.active").text();
      const priority = $(this).data("priority");
      $("#planList").append(`<li>${name} — شدت ${intensity}${priority ? " — اولویت " + priority : ""}</li>`);
    });
    $("#planSummary").text(
      count === 0 ? "هنوز درمانی انتخاب نشده است." : `${count} درمان انتخاب شده است.`
    );
    updateAfter();
  }
});
