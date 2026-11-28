/* clinic-face-ai — jQuery frontend.
   Upload -> POST /api/analyze (demo JSON for now) -> render Glow Score,
   metrics, zones and treatment cards. Doctor toggles build the plan live. */

$(function () {
  const INTENSITIES = ["خفیف", "متعادل", "محسوس"];
  const ZONE_POS = { 1: [50, 18], 2: [50, 32], 3: [50, 44], 4: [50, 62], 5: [50, 78] };
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
    const levels = { "خفیف": 1, "متعادل": 2, "محسوس": 3 };
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
    $("#afterCard").prop("hidden", count === 0);
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

  $("#compareSlider").on("input", function () {
    $("#beforeWrap").css("clip-path", `inset(0 ${100 - this.value}% 0 0)`);
  });
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
    $("#resultCard, #zonesCard, #treatmentsCard, #planCard").prop("hidden", false);
    const src = $("#photoPreview").attr("src");
    if (src) { $("#afterImg, #beforeImg").attr("src", src); $("#afterImg").css("filter", ""); }
    $("#simulateStatus").text("تا وقتی عکس واقعی ساخته نشده، پیش‌نمایش با فیلتر نمایشی است. هر عکس واقعی حدود ۰٫۰۳۴ دلار هزینه دارد.");
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
    data.metrics.forEach((m) => {
      $("#metrics").append(
        `<div class="metric"><span>${m.label}</span>` +
        `<span class="bar"><i style="width:${m.value}%"></i></span>` +
        `<b>${m.value}٪</b></div>`
      );
    });

    $("#zoneChips").empty(); $("#zoneMarkers").empty();
    data.zones.forEach((z) => {
      $("#zoneChips").append(`<button class="chip" data-id="${z.id}" type="button">${z.name}</button>`);
      const [left, top] = ZONE_POS[z.id] || [50, 50];
      $("#zoneMarkers").append(
        `<span class="zone-dot" data-id="${z.id}" style="left:${left}%; top:${top}%">${z.id}</span>`
      );
    });
    selectZone(data.zones[0].id);

    $("#treatments").empty();
    data.treatments.forEach((t) => {
      const buttons = INTENSITIES.map((label, i) =>
        `<button type="button" data-intensity="${label}" class="${i === 1 ? "active" : ""}">${label}</button>`
      ).join("");
      $("#treatments").append(
        `<div class="treatment" data-id="${t.id}">
          <h3>${t.name}</h3>
          <div class="intensity">${buttons}</div>
          <label class="doctor-toggle"><input type="checkbox" class="doctor-check"> انتخاب پزشک</label>
        </div>`
      );
    });
    updatePlan();
  }

  function selectZone(id) {
    selectedZone = id;
    $(".chip, .zone-dot").removeClass("active");
    $(`.chip[data-id="${id}"], .zone-dot[data-id="${id}"]`).addClass("active");
    const z = analysis.zones.find((item) => item.id === id);
    $("#zoneNote").text(z ? `${z.name}${z.value != null ? ": " + z.value + "٪" : ""} — ${z.note}` : "");
  }

  $(document).on("click", ".chip, .zone-dot", function () {
    selectZone(Number($(this).data("id")));
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
      $("#planList").append(`<li>${name} — شدت ${intensity}</li>`);
    });
    $("#planSummary").text(
      count === 0 ? "هنوز درمانی انتخاب نشده است." : `${count} درمان انتخاب شده است.`
    );
    updateAfter();
  }
});
