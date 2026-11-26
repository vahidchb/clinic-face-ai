/* clinic-face-ai — jQuery frontend.
   Upload -> POST /api/analyze (demo JSON for now) -> render Glow Score,
   metrics, zones and treatment cards. Doctor toggles build the plan live. */

$(function () {
  const INTENSITIES = ["خفیف", "متعادل", "محسوس"];
  const ZONE_POS = { 1: [50, 18], 2: [50, 32], 3: [50, 44], 4: [50, 62], 5: [50, 78] };
  let analysis = null;
  let selectedZone = null;
  const plan = {}; // treatmentId -> { name, intensity }

  function showPhoto(src) {
    $("#photoPreview").attr("src", src).prop("hidden", false);
    $("#photoPlaceholder").hide();
    $("#analyzeBtn").prop("disabled", false);
    $("#uploadHint").text("عکس آماده است — «شروع تحلیل» را بزنید.");
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

  $("#analyzeBtn").on("click", function () {
    const file = $("#photoInput")[0].files[0];
    const form = new FormData();
    if (file) form.append("file", file);
    else form.append("file", new Blob(["demo"], { type: "text/plain" }), "demo.txt");

    $("#scanLine").prop("hidden", false);
    $("#analyzeBtn").prop("disabled", true).text("در حال تحلیل…");
    $.ajax({
      url: "/api/analyze", method: "POST", data: form,
      processData: false, contentType: false,
      success: render,
      error: () => $("#uploadHint").text("تحلیل انجام نشد — دوباره امتحان کنید."),
      complete: () => {
        $("#scanLine").prop("hidden", true);
        $("#analyzeBtn").prop("disabled", false).text("شروع تحلیل");
      },
    });
  });

  function render(data) {
    analysis = data;
    $("#resultCard, #zonesCard, #treatmentsCard, #planCard").prop("hidden", false);

    // Glow Score ring, animated count.
    let n = 0;
    const target = data.glow_score;
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
    $("#zoneNote").text(z ? `${z.name}: ${z.note}` : "");
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
  }
});
