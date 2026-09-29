const CAMERA = { lat: 44.183501, lon: 5.2621281, bearing: 140 };
const STATIONS = [
  { name: "Avignon", lat: 43.9493, lon: 4.8055 },
  { name: "Carpentras", lat: 44.055, lon: 5.048 },
  { name: "Orange", lat: 44.136, lon: 4.809 },
  { name: "Apt", lat: 43.876, lon: 5.396 },
  { name: "Cavaillon", lat: 43.838, lon: 5.038 },
  { name: "Pertuis", lat: 43.695, lon: 5.503 },
];
const COPY = {
  en: {
    paris: "Paris time",
    weather: "Weather",
    passes: "Passes",
    namedLine: (named, habits) => `${named} named · ${habits} habits`,
    // The menu says it shorter than the headings do. The six links spelled out
    // in full took four hundred and seventy pixels of a row that has to hold
    // the title, the readings and the buttons as well, and a reader who is
    // already looking at the menu does not need "Live webcam" to guess which
    // one is the webcam.
    navLive: "Live",
    navHistory: "History",
    navFigures: "Dataviz",
    navRelief: "3D",
    navCamera: "Camera",
    navWeather: "Weather",
    navPipeline: "Pipeline",
    prevPage: "Previous",
    nextPage: "Next",
    pages: "Pages",
    pageOf: (first, last, all) => `${first}–${last} of ${all}`,
    figures: "Dataviz",
    byHour: "By hour of the day",
    byDay: "By day of the week",
    figuresSpan: (days, all) => `${all} named passes over ${days} ${days > 1 ? "days" : "day"}, Paris time.`,
    figuresEmpty: "Nothing recorded yet.",
    weekdays: ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
    kinds: {
      vehicle: "Vehicles", person: "Pedestrians", bus: "Buses",
      fire: "Fires", plane: "Planes", other: "Other",
    },
    live: "Live webcam",
    camera: "Camera",
    cameraText: "Fixed, facing 140°.",
    pipeline: "Pipeline",
    image: "Frame",
    imageText: "1 frame/s. ffmpeg reads the HLS stream.",
    motion: "Motion",
    motionText: "OpenCV MOG2, frame scaled to 640 px. If more than 35% changes, it is light, and it is ignored. The red beacon on the summit is excluded.",
    track: "Track",
    trackText: "A compact blob, tracked for at least 3 frames.",
    class: "Class",
    classText: "YOLO11 nano, ONNX, on the crop only. Person, car, bus, truck.",
    plane: "Plane",
    planeText: "OpenSky. A callsign is kept only when that aircraft is in the camera’s view, close enough to be seen. Otherwise the history says it is not in the picture.",
    bus: "Bus",
    busText: "Trans'CoVe or ZOU. A single trip within ±15 min gives the route. Otherwise “Bus”, from a confidence of 0.6.",
    fire: "Fire",
    fireText: "On the slope, 5 s, area ×1.5, at least 8% warm pixels or a rising plume. Not at dusk. In rain, fog, or snow, it takes 20%.",
    rest: "Unknown",
    restText: "We don't know what it is. Every movement is shown, with its photo.",
    history: "History",
    all: "All",
    planes: "Planes",
    vehicles: "Vehicles",
    pedestrians: "Pedestrians",
    buses: "Buses",
    fires: "Fires",
    motions: "Motion",
    habits: "Habits",
    empty: "Nothing yet.",
    compare: "Weather",
    colTime: "Time",
    colPhoto: "Photo",
    colEvent: "Event",
    colPlace: "Place",
    colReading: "Reading",
    places: {
      road: "Road", roundabout: "Roundabout", parking: "Car park", path: "Path",
      meadow: "Meadow", forest: "Forest", building: "Building", slope: "Slope",
      sky: "Sky", island: "Roundabout island", scree: "Scree", playground: "Playground", pool: "Swimming pool", other: "Off the road",
    },
    reliefWake: "Click to turn the view",
    follow: "its track",
    nearestStation: "Nearest weather station:",
    from: "from",
    to: "towards",
    heading: "heading",
    climbing: "climbing",
    descending: "descending",
    notInFrame: "Not in the picture",
    colCam: "Webcam",
    colApi: "Station",
    compareEmpty: "No reading yet.",
    repoPrivate: "Source and history of every change.",
    relief: "3D view",
    reliefBack: "Webcam angle",
    reliefWide: "Full screen",
    skip: "Skip to content",
    sections: "Sections",
    theme: "Dark mode",
    themeBack: "Light mode",
    chart: [
      ["Stream", "HLS, 1 frame a second"],
      ["Motion", "MOG2 at 640 px"],
      ["Track", "3 frames, compact"],
      ["Class", "YOLO11n on the crop"],
      ["Ground", "Surface and distance"],
      ["Name", "The rules decide"],
      ["Published", "Only what is named"],
    ],
    chartJoin: ["OpenSky", "Trans'CoVe / ZOU", "OpenStreetMap"],
    chartAsk: "Asked only when naming",
    periods: { day: "Day", twilight: "Dusk", night: "Night" },
    moon: "Moon",
    wind: "Wind",
    humidity: "Humidity",
    around: "Around",
    people: "people",
    clip: "Clip",
    scoreLine: (all, read, right) =>
      `${all} published · ${read} reviewed · ${right} right as published`,
    cameraFixed: "Fixed, facing",
    cameraField: "field",
    right: "Right",
    wrong: "Wrong",
    carWord: "Car",
    vanWord: "Lorry",
    busWord: "Bus",
    walkerWord: "Walker",
    cycleWord: "Bike",
    confirmed: "confirmed",
    rejected: "rejected",
    fireNote: "A warm patch grew. This is not an alert.",
    weatherCodes: {
      0: "Clear", 1: "Clear", 2: "Cloudy", 3: "Overcast",
      45: "Fog", 48: "Fog", 51: "Drizzle", 53: "Drizzle", 55: "Drizzle",
      61: "Light rain", 63: "Rain", 65: "Heavy rain", 71: "Light snow",
      73: "Snow", 75: "Heavy snow", 77: "Graupel", 80: "Showers", 81: "Showers",
      82: "Heavy showers", 85: "Snow showers", 86: "Snow showers",
      95: "Thunderstorm", 96: "Thunderstorm", 99: "Violent thunderstorm",
    },
  },
  fr: {
    paris: "Heure de Paris",
    weather: "Météo",
    passes: "Passages",
    namedLine: (named, habits) => `${named} nommés · ${habits} habitudes`,
    navLive: "Direct",
    navHistory: "Historique",
    navFigures: "Dataviz",
    navRelief: "3D",
    navCamera: "Caméra",
    navWeather: "Météo",
    navPipeline: "Pipeline",
    prevPage: "Précédent",
    nextPage: "Suivant",
    pages: "Pages",
    pageOf: (first, last, all) => `${first}–${last} sur ${all}`,
    figures: "Dataviz",
    byHour: "Par heure de la journée",
    byDay: "Par jour de la semaine",
    figuresSpan: (days, all) => `${all} passages nommés sur ${days} jour${days > 1 ? "s" : ""}, heure de Paris.`,
    figuresEmpty: "Rien d'enregistré pour l'instant.",
    weekdays: ["lun", "mar", "mer", "jeu", "ven", "sam", "dim"],
    kinds: {
      vehicle: "Véhicules", person: "Piétons", bus: "Bus",
      fire: "Feux", plane: "Avions", other: "Autres",
    },
    live: "Webcam en direct",
    camera: "Caméra",
    cameraText: "Fixe, vers 140°.",
    pipeline: "Pipeline",
    image: "Image",
    imageText: "1 image/s. ffmpeg lit le flux HLS.",
    motion: "Mouvement",
    motionText: "OpenCV MOG2, image ramenée à 640 px. Si plus de 35 % change, c’est la lumière, on ignore. La balise rouge du sommet est exclue.",
    track: "Suivi",
    trackText: "Une tache compacte, suivie au moins de 3 images.",
    class: "Classe",
    classText: "YOLO11 nano, en ONNX, seulement sur le rectangle. Personne, voiture, bus, camion.",
    plane: "Avion",
    planeText: "OpenSky. L’indicatif n’est gardé que si l’avion est dans le champ, assez près pour être vu. Sinon l’historique dit qu’il n’est pas dans l’image.",
    bus: "Bus",
    busText: "Trans'CoVe ou ZOU. Une seule course à ±15 min donne la ligne. Sinon « Bus », à partir d’une confiance de 0,6.",
    fire: "Feu",
    fireText: "Sur la pente, 5 s, surface ×1,5, au moins 8 % de pixels chauds ou un panache qui monte. Au crépuscule, non. Sous la pluie, le brouillard ou la neige, il faut 20 %.",
    rest: "Inconnu",
    restText: "On ne sait pas ce que c’est. Chaque mouvement est affiché, avec sa photo.",
    history: "Historique",
    all: "Tout",
    planes: "Avions",
    vehicles: "Véhicules",
    pedestrians: "Piétons",
    buses: "Bus",
    fires: "Incendies",
    motions: "Mouvements",
    habits: "Habitudes",
    empty: "Rien pour l’instant.",
    compare: "Météo",
    colTime: "Heure",
    colPhoto: "Photo",
    colEvent: "Événement",
    colPlace: "Lieu",
    colReading: "Lecture",
    places: {
      road: "Chaussée", roundabout: "Rond-point", parking: "Parking", path: "Sentier",
      meadow: "Prairie", forest: "Forêt", building: "Bâti", slope: "Pente",
      sky: "Ciel", island: "Îlot central", scree: "Éboulis", playground: "Aire de jeux", pool: "Piscine", other: "Hors chaussée",
    },
    reliefWake: "Cliquer pour tourner la vue",
    follow: "sa trace",
    nearestStation: "Station météo la plus proche :",
    from: "de",
    to: "vers",
    heading: "cap",
    climbing: "en montée",
    descending: "en descente",
    notInFrame: "Pas dans l'image",
    colCam: "Webcam",
    colApi: "Station",
    compareEmpty: "Pas encore de relevé.",
    repoPrivate: "Le code et l’histoire de chaque changement.",
    relief: "Vue 3D",
    reliefBack: "Angle webcam",
    reliefWide: "Plein écran",
    skip: "Aller au contenu",
    sections: "Sections",
    theme: "Mode sombre",
    themeBack: "Mode clair",
    chart: [
      ["Flux", "HLS, une image par seconde"],
      ["Mouvement", "MOG2 à 640 px"],
      ["Piste", "3 images, compacte"],
      ["Classe", "YOLO11n sur la découpe"],
      ["Sol", "Surface et distance"],
      ["Nom", "Les règles tranchent"],
      ["Publié", "Rien que le nommé"],
    ],
    chartJoin: ["OpenSky", "Trans'CoVe / ZOU", "OpenStreetMap"],
    chartAsk: "Interrogé seulement pour nommer",
    periods: { day: "Jour", twilight: "Crépuscule", night: "Nuit" },
    moon: "Lune",
    wind: "Vent",
    humidity: "Humidité",
    around: "Autour",
    people: "personnes",
    clip: "Extrait",
    scoreLine: (all, read, right) =>
      `${all} publications · ${read} relues · ${right} juste${right > 1 ? "s" : ""} du premier coup`,
    cameraFixed: "Fixe, cap",
    cameraField: "champ",
    right: "Juste",
    wrong: "Faux",
    carWord: "Voiture",
    vanWord: "Camion",
    busWord: "Bus",
    walkerWord: "Piéton",
    cycleWord: "Vélo",
    confirmed: "validé",
    rejected: "rejeté",
    fireNote: "Tache chaude qui a grossi. Ce n’est pas une alerte.",
    weatherCodes: {
      0: "Ciel dégagé", 1: "Dégagé", 2: "Nuageux", 3: "Couvert",
      45: "Brouillard", 48: "Brouillard", 51: "Bruine", 53: "Bruine", 55: "Bruine",
      61: "Pluie légère", 63: "Pluie", 65: "Forte pluie", 71: "Neige légère",
      73: "Neige", 75: "Forte neige", 77: "Grésil", 80: "Averses", 81: "Averses",
      82: "Fortes averses", 85: "Averses de neige", 86: "Averses de neige",
      95: "Orage", 96: "Orage", 99: "Orage violent",
    },
  },
};

const LABELS = {
  "Voiture": "Car",
  "Voiture et piéton": "Car and pedestrian",
  "Camion": "Truck",
  "Véhicule": "Vehicle",
  "Camping-car": "Camper van",
  "Incendie": "Fire",
  "Habitude du cadrage": "Habit of the frame",
  "Mouvement": "Motion",
  "Mouvement sur la route": "Motion on the road",
  "Mouvement dans le ciel": "Motion in the sky",
  "Masse dans le ciel": "Mass in the sky",
  "Point dans le ciel": "Point in the sky",
  "Presque immobile": "Almost still",
  "Véhicule incertain": "Uncertain vehicle",
  "Piéton": "Pedestrian",
  "Piétons": "Pedestrians",
  "Vélo": "Bicycle",
  "Moto": "Motorbike",
  "Deux-roues": "Two-wheeler",
  "Piétons et une voiture": "Pedestrians and a car",
  "Voiture et piétons": "A car and pedestrians",
  "Deux véhicules et un piéton": "Two vehicles and a pedestrian",
  "Soleil bas dans les arbres": "Low sun in the trees",
  "Mouvement devant le relief": "Motion against the hillside",
  "Chien": "Dog",
  "Cheval": "Horse",
  "Piétons doublés par une voiture": "Pedestrians overtaken by a car",
  "Avion non identifié": "Unidentified aircraft",
  "Voiture blanche": "White car",
  "Estafette": "Van",
  "Camionnette blanche": "White van",
  "Voiture avec carriole": "Car with a trailer",
  "Repère éclairé": "Lit landmark",
  "Mouvement hors chaussée": "Motion off the road",
  "Tache trop large": "Patch too wide",
  "Départ de feu": "Fire starting",
  "Masse sur la pente": "Mass on the slope",
  "Camionnette": "Van",
  "Voiture garée": "Parked car",
  "Lueur du soir": "Evening glow",
  "Simulation : incendie": "Simulation: fire",
  "Simulation : départ de feu": "Simulation: fire starting",
  "Motif sur la chaussée": "Pattern on the roadway",
  "Décor de l’îlot": "Roundabout island furniture",
  "Lueur dans la météo": "Glow in the weather",
};

let lang = localStorage.getItem("ventoux-lang") === "fr" ? "fr" : "en";
let weatherNow = null;
let bulletin = null;

const SKY = {
  "ciel dégagé": "Clear",
  "peu nuageux": "Partly cloudy",
  "couvert": "Overcast",
  "brouillard": "Fog",
  "pluie": "Rain",
  "neige": "Snow",
  "orage": "Thunderstorm",
  "nuit": "Night",
};
let counts = null;

function t(key) {
  return COPY[lang][key];
}

function locale() {
  return lang === "fr" ? "fr-FR" : "en-GB";
}

// The 3D view is a separate module and must not keep a second copy of the
// wording: one dictionary, or the same place ends up named two ways.
const THEME_KEY = "ventoux-theme";
let theme = localStorage.getItem(THEME_KEY)
  || (window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light");

function applyTheme() {
  document.documentElement.dataset.theme = theme;
  const knob = document.getElementById("theme");
  if (!knob) return;
  const next = theme === "dark" ? t("themeBack") : t("theme");
  knob.textContent = theme === "dark" ? "☀" : "◐";
  knob.title = next;
  knob.setAttribute("aria-label", next);
  knob.setAttribute("aria-pressed", String(theme === "dark"));
}

document.getElementById("theme")?.addEventListener("click", () => {
  theme = theme === "dark" ? "light" : "dark";
  localStorage.setItem(THEME_KEY, theme);
  applyTheme();
});
document.addEventListener("ventoux-lang", applyTheme);
applyTheme();

window.ventoux = {
  locale,
  place: (key) => t("places")[key] || key,
  period: (key) => t("periods")[key] || key,
};

function drawChart() {
  const chart = document.getElementById("chart");
  if (!chart) return;
  const steps = t("chart").map(([name, note], turn) => {
    const last = turn === t("chart").length - 1 ? " out" : "";
    return `<div class="step${last}"><b>${name}</b><span>${note}</span></div>`;
  });
  // On their own line, and never in the chain. These are asked at the naming
  // step and nowhere else: a callsign or a timetable never decides that
  // something moved, only what to call it once it has.
  const joins = t("chartJoin").map((name) => `<span class="join">${name}</span>`);
  chart.innerHTML = `<div class="flow">${steps.join("")}</div>`
    + `<p class="asks"><span class="lab">${t("chartAsk")}</span>${joins.join("")}</p>`;
}

function applyLang() {
  queueMicrotask(() => document.dispatchEvent(new CustomEvent("ventoux-lang")));
  document.documentElement.lang = lang;
  drawChart();
  document.querySelectorAll("[data-i18n]").forEach((node) => {
    const value = t(node.dataset.i18n);
    if (typeof value === "string") node.textContent = value;
  });
  document.querySelectorAll("[data-i18n-title]").forEach((node) => {
    node.title = t(node.dataset.i18nTitle);
    node.setAttribute("aria-label", t(node.dataset.i18nTitle));
  });
  document.querySelectorAll("[data-i18n-aria]").forEach((node) => {
    node.setAttribute("aria-label", t(node.dataset.i18nAria));
  });
  document.querySelectorAll(".langs button").forEach((button) => {
    button.classList.toggle("on", button.dataset.lang === lang);
  });
  tick();
  paintCamera();
  paintWeather();
  paintBulletin();
  paintCounts();
  render();
  paintFigures();
  paintSequence();
}

document.querySelectorAll(".langs button").forEach((button) => {
  button.addEventListener("click", () => {
    lang = button.dataset.lang === "fr" ? "fr" : "en";
    localStorage.setItem("ventoux-lang", lang);
    applyLang();
  });
});

function km(a, b) {
  const rad = Math.PI / 180;
  const dLat = (b.lat - a.lat) * rad;
  const dLon = (b.lon - a.lon) * rad;
  const h = Math.sin(dLat / 2) ** 2
    + Math.cos(a.lat * rad) * Math.cos(b.lat * rad) * Math.sin(dLon / 2) ** 2;
  return 6371 * 2 * Math.asin(Math.sqrt(h));
}

const station = STATIONS.slice().sort((a, b) => km(CAMERA, a) - km(CAMERA, b))[0];

function tick() {
  const now = new Date();
  document.querySelector("#clock").textContent = now.toLocaleTimeString(locale(), {
    timeZone: "Europe/Paris", hour: "2-digit", minute: "2-digit",
  });
  document.querySelector("#clock-date").textContent = now.toLocaleDateString(locale(), {
    timeZone: "Europe/Paris", weekday: "short", day: "numeric", month: "short",
  });
}

function mapLink(spot) {
  return `https://www.openstreetmap.org/?mlat=${spot.lat}&mlon=${spot.lon}#map=14/${spot.lat}/${spot.lon}`;
}

function escapeText(word) {
  return String(word).replace(/[&<>"]/g, (mark) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[mark]));
}

function stationLabel() {
  // The camera before the station. The forecast is modelled on a grid whose
  // ground here lies a thousand metres below the lens, so it answers for the
  // valley: it read "clear" from dusk to dawn on 26 September while the crest
  // of the Ventoux was nowhere in the picture. The bulletin is read off the
  // webcam itself, and where the two disagree the webcam is the one standing
  // on the mountain.
  if (bulletin && bulletin.webcam && bulletin.webcam !== "nuit") return skyText(bulletin.webcam);
  return weatherNow ? t("weatherCodes")[weatherNow.code] || "" : "";
}

function paintWeather() {
  // Everything about the weather now reads in the weather section: which
  // station, how far, the wind, the humidity. The bar at the top keeps the one
  // line anybody glances at, and the temperature carries the sky with it
  // rather than trailing a note underneath. Four stacked lines up there cost
  // fifty pixels of every section on the page, every time anyone scrolled.
  const more = document.querySelector("#view-air");
  if (weatherNow) {
    const sky = stationLabel();
    document.querySelector("#weather").textContent =
      [Number.isFinite(weatherNow.temp) ? `${weatherNow.temp} °C` : "—", sky].filter(Boolean).join(" · ");
  }
  if (more && weatherNow) {
    more.textContent = [
      Number.isFinite(weatherNow.wind) ? `${t("wind")} ${weatherNow.wind} km/h` : "",
      Number.isFinite(weatherNow.humidity) ? `${t("humidity")} ${weatherNow.humidity} %` : "",
    ].filter(Boolean).join(" · ");
  }
  paintBulletin();
}

function skyText(value) {
  if (!value) return "";
  if (lang === "fr") return value.charAt(0).toUpperCase() + value.slice(1);
  return SKY[value] || value;
}

function paintBulletin() {
  const words = document.querySelector("#view-words");
  const when = document.querySelector("#view-when");
  const photo = document.querySelector("#view-photo");
  const shot = document.querySelector("#view-shot");
  const moon = document.querySelector("#view-moon");
  const place = document.querySelector("#view-station");
  if (!words || !when || !photo || !place) return;
  if (!bulletin || !bulletin.t) {
    words.textContent = t("compareEmpty");
    when.textContent = "";
    if (shot) shot.hidden = true;
    // Still say who the station is. It used to be named in the bar at the top
    // as well, and with that gone this is the only place it appears: emptying
    // the line would take the reading's source off the page altogether.
    place.innerHTML = stationLine();
    return;
  }
  when.textContent = new Date(bulletin.t).toLocaleString(locale(), {
    timeZone: "Europe/Paris", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit",
  });
  words.textContent = [
    t("periods")[bulletin.period] || "",
    bulletin.moon ? t("moon") : "",
    skyText(bulletin.webcam),
  ].filter(Boolean).join(" · ");
  if (bulletin.photo) {
    photo.src = `${bulletin.photo}?t=${encodeURIComponent(bulletin.t)}`;
    if (shot) shot.hidden = false;
  }
  // The words say there is a moon; this says which of the bright specks it is.
  // The watcher already found the disc to say so, and kept where it was.
  const at = bulletin.moon_at;
  if (moon) {
    moon.hidden = !at;
    if (at) {
      moon.style.left = `${at.cx * 100}%`;
      moon.style.top = `${at.cy * 100}%`;
      moon.style.width = `${Math.max(at.r * 2 * 100, 4)}%`;
      moon.title = t("moon");
    }
  }
  // Who is speaking, and from how far. A reading that disagrees with the
  // picture above it is only worth arguing with once you know it was taken
  // twenty-two kilometres away and eleven hundred metres lower.
  const reading = [
    Number.isFinite(bulletin.temp_c) ? `${bulletin.temp_c} °C` : "",
    skyText(bulletin.api) || stationLabel(),
  ].filter(Boolean).join(" · ");
  place.innerHTML = stationLine(reading);
}

function stationLine(reading) {
  return `${t("nearestStation")} <a class="out" href="${mapLink(station)}" target="_blank" rel="noopener">${escapeText(station.name)}</a>`
    + ` · ${escapeText(`${Math.round(km(CAMERA, station))} km`)}`
    + (reading ? ` · ${escapeText(reading)}` : "");
}

async function loadView() {
  try {
    const response = await fetch("data/view.json", { cache: "no-store" });
    if (!response.ok) return;
    const payload = await response.json();
    bulletin = payload.last || null;
    // Not paintBulletin alone: the bar at the top quotes the webcam too now.
    paintWeather();
  } catch (_) {
    /* The card fills once the watcher has read the sky. */
  }
}

async function loadWeather() {
  paintWeather();
  try {
    const url = `https://api.open-meteo.com/v1/forecast?latitude=${station.lat}&longitude=${station.lon}`
      + "&current=temperature_2m,weather_code,relative_humidity_2m,wind_speed_10m&timezone=Europe/Paris";
    const data = await fetch(url, { cache: "no-store" }).then((response) => response.json());
    const current = data.current || {};
    weatherNow = {
      temp: Math.round(current.temperature_2m),
      code: current.weather_code,
      humidity: Math.round(current.relative_humidity_2m),
      wind: Math.round(current.wind_speed_10m),
    };
    paintWeather();
  } catch (_) {
    document.querySelector("#weather").textContent = "—";
  }
}

const STREAM = "https://visionenvironnement.quanteec.com/contents/encodings/live/78e0f372-db6f-420e-746c-7561-6665-64-b4d7-fc979b816efed/master.m3u8";
const FALLBACK = "https://s1.vision-environnement.com/live/modules/timelapse/timelapse/montserein.mp4";

const video = document.querySelector("#player");
if (window.Hls && Hls.isSupported()) {
  const hls = new Hls();
  hls.loadSource(STREAM);
  hls.attachMedia(video);
  hls.on(Hls.Events.ERROR, (_, data) => {
    if (data.fatal) video.src = FALLBACK;
  });
} else {
  video.src = video.canPlayType("application/vnd.apple.mpegurl") ? STREAM : FALLBACK;
}

const list = document.querySelector("#list");
const empty = document.querySelector("#empty");
let events = [];
let filter = "all";
// A page of the log, not the whole of it. Eight thousand passes make a table
// forty thousand pixels tall, which is a section no reader ever reaches the
// foot of and a page no browser lays out quickly.
const PER_PAGE = 25;
let page = 0;

const loupe = document.querySelector("#loupe");
const loupeImg = loupe.querySelector("img");

function moveLoupe(event) {
  const pad = 12;
  const box = loupe.getBoundingClientRect();
  let x = event.clientX + 20;
  let y = event.clientY - box.height / 2;
  if (x + box.width > window.innerWidth - pad) x = event.clientX - box.width - 20;
  if (y < pad) y = pad;
  if (y + box.height > window.innerHeight - pad) y = Math.max(pad, window.innerHeight - box.height - pad);
  loupe.style.left = `${x}px`;
  loupe.style.top = `${y}px`;
}

list.addEventListener("mouseover", (event) => {
  const img = event.target.closest(".shot img");
  if (!img) return;
  loupeImg.src = img.src;
  loupe.hidden = false;
  moveLoupe(event);
});
list.addEventListener("mousemove", (event) => {
  if (!loupe.hidden && event.target.closest(".shot img")) moveLoupe(event);
});
list.addEventListener("mouseout", (event) => {
  if (event.target.closest(".shot img")) loupe.hidden = true;
});

document.querySelectorAll(".filters button").forEach((button) => {
  button.addEventListener("click", () => {
    filter = button.dataset.filter;
    page = 0;
    document.querySelectorAll(".filters button").forEach((item) => item.classList.toggle("on", item === button));
    render();
  });
});

document.querySelector("#pager")?.addEventListener("click", (hit) => {
  const step = hit.target.closest("button")?.dataset.step;
  if (!step) return;
  page += Number(step);
  render();
  // Back to the head of the log, otherwise turning the page leaves the reader
  // looking at the foot of a table whose rows have all changed under them.
  document.querySelector("#log")?.scrollIntoView({ behavior: "smooth", block: "start" });
});

function who(info) {
  // The airline and flight number when the code is one we know, the raw
  // callsign otherwise. Never both: repeating AAL746 after "American Airlines
  // 746" tells the reader nothing they have not just read.
  if (info.operator && info.flight) return escapeText(`${info.operator} ${info.flight}`);
  return escapeText(info.callsign || "OpenSky");
}

function route(info) {
  // One end is worth printing on its own: an aircraft still in the air has no
  // filed arrival yet, and "from Philadelphia" is the whole story anyway.
  const from = info.from_town || info.from;
  const to = info.to_town || info.to;
  if (from && to) return `${escapeText(from)} → ${escapeText(to)}`;
  if (from) return `${t("from")} ${escapeText(from)}`;
  if (to) return `${t("to")} ${escapeText(to)}`;
  return "";
}

function facts(info) {
  const out = [];
  if (info.altitude_m != null) out.push(`${Math.round(info.altitude_m).toLocaleString(locale())} m`);
  if (info.speed_ms != null) out.push(`${Math.round(info.speed_ms * 3.6).toLocaleString(locale())} km/h`);
  if (info.heading != null) out.push(`${t("heading")} ${Math.round(info.heading)}°`);
  // A tenth of a metre a second is level flight; below that the reading is the
  // instrument breathing, not the aircraft going anywhere.
  if (info.climb_ms != null && Math.abs(info.climb_ms) >= 1) {
    out.push(info.climb_ms > 0 ? t("climbing") : t("descending"));
  }
  if (info.distance_km != null) out.push(`${Math.round(info.distance_km)} km`);
  return out;
}

function detail(event) {
  const info = event.detail || {};
  if (event.type === "plane") {
    const place = info.seen ? "" : t("notInFrame");
    // No weather and no time of day here: the photograph beside this line
    // already says both, and said in words they would need translating twice.
    // The name is already the heading of this row when nothing better than
    // the callsign was known, and saying it twice says nothing twice.
    const name = who(info);
    const words = [name === escapeText(showText(event.label)) ? "" : name,
      route(info), ...facts(info), place].filter(Boolean).join(" · ");
    // Where to go and check. OpenSky named this aircraft but has retired its
    // own website, so the link goes to a tracker that still answers, and asks
    // it for the trace of the day we saw it rather than for a live position:
    // the aircraft has long landed, and what is worth checking is the path it
    // flew over this ridge at that hour.
    if (!info.icao24) return words;
    const day = new Date(event.t).toISOString().slice(0, 10);
    const track = `https://globe.adsbexchange.com/?icao=${encodeURIComponent(info.icao24)}&showTrace=${day}`;
    return `${words} · <a class="out" href="${track}" target="_blank" rel="noopener">${t("follow")}</a>`;
  }
  if (event.type === "bus" && info.route) {
    return `${info.headsign || info.route} · ${info.scheduled || ""} · ${info.source || ""}`.trim();
  }
  if (event.type === "fire") return showText(info.reading) || t("fireNote");
  if (info.reading) return [showText(info.context), showText(info.reading)].filter(Boolean).join(" · ");
  if (info.context) return showText(info.context);
  return "";
}

function render() {
  const shown = events.filter((event) => {
    if (filter === "all") return true;
    if (filter === "vehicle") return event.type === "vehicle" || event.type === "car";
    return event.type === filter;
  });
  empty.hidden = shown.length > 0;
  const count = document.querySelector("#count");
  const right = shown.filter((event) => event.review !== "rejected").length;
  if (count) count.textContent = right ? String(right) : "";
  paintScore();
  const pages = Math.max(1, Math.ceil(shown.length / PER_PAGE));
  page = Math.min(Math.max(page, 0), pages - 1);
  const pager = document.querySelector("#pager");
  if (pager) {
    pager.hidden = shown.length <= PER_PAGE;
    const where = pager.querySelector("#pager-where");
    const first = page * PER_PAGE + 1;
    const last = Math.min((page + 1) * PER_PAGE, shown.length);
    if (where) where.textContent = t("pageOf")(first, last, shown.length);
    pager.querySelector('[data-step="-1"]').disabled = page === 0;
    pager.querySelector('[data-step="1"]').disabled = page >= pages - 1;
  }
  list.innerHTML = shown.slice(page * PER_PAGE, (page + 1) * PER_PAGE).map((event) => {
    const moment = new Date(event.t);
    const clock = moment.toLocaleTimeString(locale(), { hour: "2-digit", minute: "2-digit", second: "2-digit", timeZone: "Europe/Paris" });
    const day = moment.toLocaleDateString(locale(), { day: "2-digit", month: "short", year: "numeric", timeZone: "Europe/Paris" });
    const picture = event.thumb
      ? `<img src="${escapeHtml(event.thumb)}" alt="" loading="lazy" decoding="async">`
      : `<span class="placeholder"></span>`;
    const info = event.detail || {};
    const people = Number(info.persons || 0);
    const title = people > 1 ? `${showText(event.label)} (${people})` : showText(event.label);
    // Only for aircraft. The rest of this log is a time, a word and a picture
    // on purpose; an aircraft is the one thing here that cannot be checked by
    // looking, so it carries its numbers and the place they came from.
    const extra = event.type === "plane" ? `<span class="sub">${detail(event)}</span>` : "";
    const place = t("places")[info.surface || event.zone] || "";
    // Une lecture que vous avez dite fausse reste ici, barrée. La retirer
    // ferait une belle page et un mauvais registre : on ne peut pas viser le
    // zéro faute en effaçant les fautes, et c'est de celles-là qu'on apprend.
    const wrong = event.review === "rejected" ? ' class="wrong"' : "";
    return `<tr${wrong}><td class="when"><time>${clock}</time><span>${day}</span></td>`
      + `<td class="event">${escapeHtml(title)}${extra}</td>`
      + `<td class="place">${escapeHtml(place)}</td>`
      + `<td class="shot">${picture}</td></tr>`;
  }).join("");
}

// The order the bars are stacked in, bottom first, and the order the legend
// reads. Fixed rather than taken from the data, so a quiet day does not
// reshuffle the colours and make two charts impossible to compare.
const KINDS = ["vehicle", "person", "bus", "fire", "plane", "other"];

function kindOf(event) {
  if (event.type === "car") return "vehicle";
  return KINDS.includes(event.type) ? event.type : "other";
}

// Paris time, because that is the clock the history is written in and the one
// the hillside lives by. Reading the hour off the browser would put a visitor
// in California nine hours out and make the busiest hour of the day midnight.
function parisParts(stamp) {
  const bits = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Europe/Paris", weekday: "short", hour: "2-digit", hour12: false,
    year: "numeric", month: "2-digit", day: "2-digit",
  }).formatToParts(new Date(stamp));
  const get = (kind) => bits.find((part) => part.type === kind)?.value || "";
  const days = { Mon: 0, Tue: 1, Wed: 2, Thu: 3, Fri: 4, Sat: 5, Sun: 6 };
  return {
    hour: Number(get("hour")) % 24,
    day: days[get("weekday")] ?? 0,
    date: `${get("year")}-${get("month")}-${get("day")}`,
  };
}

function paintFigures() {
  const hourBox = document.querySelector("#by-hour");
  const dayBox = document.querySelector("#by-day");
  const legend = document.querySelector("#figures-legend");
  const span = document.querySelector("#figures-span");
  if (!hourBox || !dayBox || !legend || !span) return;
  // A drawn fire is not a fire that happened. These figures are meant to say
  // what goes past this camera at which hour, and a simulation went past
  // nothing: the two on file were the only entries in the "fire" column and
  // gave it 0.7 % of the whole.
  const seen = events.filter((event) => !(event.detail || {}).simulation && event.review !== "rejected");
  if (!seen.length) {
    span.textContent = t("figuresEmpty");
    hourBox.innerHTML = dayBox.innerHTML = legend.innerHTML = "";
    return;
  }
  const hours = Array.from({ length: 24 }, () => ({}));
  const days = Array.from({ length: 7 }, () => ({}));
  const whole = {};
  const dates = new Set();
  for (const event of seen) {
    const kind = kindOf(event);
    const when = parisParts(event.t);
    dates.add(when.date);
    hours[when.hour][kind] = (hours[when.hour][kind] || 0) + 1;
    days[when.day][kind] = (days[when.day][kind] || 0) + 1;
    whole[kind] = (whole[kind] || 0) + 1;
  }
  span.textContent = t("figuresSpan")(dates.size, seen.length);
  legend.innerHTML = KINDS.filter((kind) => whole[kind]).map((kind) =>
    `<span class="key"><i style="background:var(--cat-${kind})"></i>${escapeHtml(t("kinds")[kind])}`
    + ` <b>${share(whole[kind], seen.length)}</b></span>`).join("");
  hourBox.innerHTML = bars(hours, seen.length, (index) => String(index).padStart(2, "0"));
  dayBox.innerHTML = bars(days, seen.length, (index) => t("weekdays")[index]);
}

function share(part, all) {
  if (!all) return "0 %";
  const value = (part / all) * 100;
  return `${value >= 10 ? Math.round(value) : value.toFixed(1)} %`;
}

function bars(buckets, all, label) {
  // Heights are read against the busiest bucket, so the tallest bar fills the
  // panel whatever the totals are; the number printed on it is the share of
  // everything, which is the figure that means something on its own.
  const totals = buckets.map((bucket) => Object.values(bucket).reduce((sum, n) => sum + n, 0));
  const peak = Math.max(1, ...totals);
  return buckets.map((bucket, index) => {
    const total = totals[index];
    const parts = KINDS.filter((kind) => bucket[kind]).map((kind) =>
      `<i style="flex:${bucket[kind]};background:var(--cat-${kind})"></i>`).join("");
    const told = KINDS.filter((kind) => bucket[kind])
      .map((kind) => `${t("kinds")[kind]} ${bucket[kind]}`).join(" · ");
    return `<div class="bar" title="${escapeHtml(`${label(index)} — ${share(total, all)}${told ? ` · ${told}` : ""}`)}">`
      + `<b class="val">${total ? share(total, all) : ""}</b>`
      + `<span class="col" style="height:${(total / peak) * 100}%">${parts}</span>`
      + `<span class="tick">${escapeHtml(label(index))}</span></div>`;
  }).join("");
}

const REVIEW_CLASSES = [
  ["voiture", "carWord", "Voiture"],
  ["camion", "vanWord", "Camion"],
  ["bus", "busWord", "Bus"],
  ["pieton", "walkerWord", "Piéton"],
  ["velo", "cycleWord", "Vélo"],
];

function reviewControls(event) {
  if (event.type === "motion") {
    const correction = (event.detail || {}).correction;
    const rejected = event.review === "rejected" ? " on" : "";
    const choices = REVIEW_CLASSES.map(([classe, word, label]) =>
      `<a class="yes${correction === label ? " on" : ""}" href="${reviewUrl(event, "accepted", "valide", classe)}">${escapeHtml(t(word))}</a>`).join("");
    return `<p class="verdict">${choices}<a class="no${rejected}" href="${reviewUrl(event, "rejected", "rejete")}">${escapeHtml(t("wrong"))}</a></p>`;
  }
  const accepted = event.review === "accepted" ? " on" : "";
  const rejected = event.review === "rejected" ? " on" : "";
  return `<p class="verdict"><a class="yes${accepted}" href="${reviewUrl(event, "accepted", "valide")}">${escapeHtml(t("right"))}</a><a class="no${rejected}" href="${reviewUrl(event, "rejected", "rejete")}">${escapeHtml(t("wrong"))}</a></p>`;
}

function reviewUrl(event, verdict, label, classe) {
  const title = `revue ${event.id}`;
  const body = `event_id: ${event.id}\nverdict: ${verdict}\nlecture: ${event.label}\n${classe ? `classe: ${classe}\n` : ""}`;
  return `https://github.com/Medialoco/ventoux-watch/issues/new?title=${encodeURIComponent(title)}&body=${encodeURIComponent(body)}&labels=${label}`;
}

// Colours are written after the word and spelt to agree with it, so English
// needs both spellings back.
const TINTS = {
  blanche: "white", blanc: "white",
  noire: "black", noir: "black",
  grise: "grey", gris: "grey",
  rouge: "red", orange: "orange", jaune: "yellow",
  verte: "green", vert: "green",
  bleue: "blue", bleu: "blue",
  marron: "brown",
};

function showText(value) {
  if (!value || lang === "fr") return value || "";
  if (LABELS[value]) return LABELS[value];
  const parts = value.split(" ");
  const tint = TINTS[parts[parts.length - 1]];
  if (tint) {
    const rest = showText(parts.slice(0, -1).join(" "));
    return `${tint.charAt(0).toUpperCase()}${tint.slice(1)} ${rest.toLowerCase()}`;
  }
  return value;
}

function paintScore() {
  // Le but est un pipeline qui ne se trompe jamais, et cela se prouve par un
  // taux plutôt que par une sélection. Le compte est tenu sur ce qui a été
  // relu : une publication que personne n'a regardée n'est ni juste ni fausse.
  const box = document.querySelector("#score");
  if (!box) return;
  const real = events.filter((event) => !(event.detail || {}).simulation);
  const read = real.filter((event) => event.review);
  // Une entrée corrigée à la main porte aujourd'hui le bon mot, mais elle
  // était fausse quand elle a été publiée, et c'est cela qu'on compte. Sans
  // cette ligne le score dirait 53 justes sur 54 en ne montrant que le travail
  // de correction : il flatterait exactement la chose qu'il est censé juger.
  const right = read.filter((event) => event.review === "accepted"
    && !(event.detail || {}).correction);
  box.textContent = t("scoreLine")(real.length, read.length, right.length);
  box.hidden = read.length === 0;
}

function paintCounts() {
  if (!counts) return;
  document.querySelector("#seen").textContent = String(counts.seen || 0);
  // The breakdown belongs beside the history it describes. In the top bar it
  // was a second line under the total, and the bar has no second line to give.
  const tally = document.querySelector("#tally");
  if (tally) tally.textContent = t("namedLine")(counts.named || 0, counts.habits || 0);
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[char]));
}

async function load() {
  const response = await fetch("data/events.json", { cache: "no-store" });
  const payload = await response.json();
  events = payload.events || [];
  const stamp = document.getElementById("version");
  if (stamp && payload.version) stamp.textContent = `v${payload.version}`;
  render();
  paintFigures();
  try {
    const learning = await fetch("data/learning.json", { cache: "no-store" });
    if (learning.ok) {
      counts = await learning.json();
      paintCounts();
    }
  } catch (_) {
    /* Le compteur apparaît quand le Pi a commencé à apprendre. */
  }
}

// Le cône n'est pas déclaré, il est mesuré. build_scene.py déplace le cap, le
// site, le champ, la hauteur et jusqu'à la position de la caméra tant que les
// dix-neuf repères OSM ne tombent pas là où on les voit dans l'image, et écrit
// le résultat dans config/scene.json. Ces trois nombres étaient écrits à la
// main ici : 140° de cap, 90° de champ, 600 m de portée, quand le calage dit
// 126,7°, 78,8° et 2500 m. Le cône montré pointait treize degrés à côté et
// s'arrêtait au quart de ce que la caméra atteint.
//
// L'écart résiduel du calage vaut 0,0136 en largeur d'image. Multiplié par le
// champ, 0,0136 × 78,755° ≈ 1,1° : c'est la précision du cap. Le calcul qui
// mène à camera:direction=127 est écrit dans scripts/build_scene.py.
const AIM_FALLBACK = { lat: 44.1833492, lon: 5.2620281, yaw: 126.713, hfov: 78.755, reach: 2500 };
let aim = AIM_FALLBACK;

function offset(lat, lon, bearing, meters) {
  const rad = Math.PI / 180;
  const distance = meters / 6371000;
  const br = bearing * rad;
  const lat1 = lat * rad;
  const lon1 = lon * rad;
  const lat2 = Math.asin(Math.sin(lat1) * Math.cos(distance) + Math.cos(lat1) * Math.sin(distance) * Math.cos(br));
  const lon2 = lon1 + Math.atan2(Math.sin(br) * Math.sin(distance) * Math.cos(lat1), Math.cos(distance) - Math.sin(lat1) * Math.sin(lat2));
  return [lat2 / rad, lon2 / rad];
}

function viewWedge() {
  const points = [[aim.lat, aim.lon]];
  const start = aim.yaw - aim.hfov / 2;
  for (let step = 0; step <= 28; step += 1) {
    points.push(offset(aim.lat, aim.lon, start + (aim.hfov * step) / 28, aim.reach));
  }
  return points;
}

// La portée du calage est de deux kilomètres et demi, mais ce qui a vraiment
// été reconnu tient entre 106 et 830 m : les trois niveaux cadrent sur cette
// bande-là, pas sur le bout du cône.
function zoomLevels() {
  return [
    { zoom: 18, along: 0 },
    { zoom: 16, along: aim.reach * 0.08 },
    { zoom: 14, along: aim.reach * 0.16 },
  ];
}

const map = L.map("map", {
  scrollWheelZoom: false,
  zoomControl: false,
  doubleClickZoom: false,
  boxZoom: false,
  keyboard: false,
  attributionControl: false,
});
L.control.attribution({ prefix: false }).addTo(map);
L.tileLayer("https://data.geopf.fr/wmts?LAYER=ORTHOIMAGERY.ORTHOPHOTOS&FORMAT=image/jpeg&SERVICE=WMTS&VERSION=1.0.0&REQUEST=GetTile&STYLE=normal&TILEMATRIXSET=PM&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}", {
  maxZoom: 19,
  attribution: "© IGN",
}).addTo(map);
const wedge = L.polygon(viewWedge(), {
  color: "#c4b094",
  weight: 1.5,
  fillColor: "#f3efe6",
  fillOpacity: 0.62,
}).addTo(map);
const axis = L.polyline([
  [aim.lat, aim.lon],
  offset(aim.lat, aim.lon, aim.yaw, aim.reach),
], { color: "#c4b094", weight: 2, dashArray: "4 6" }).addTo(map);
const cameraMark = L.circleMarker([aim.lat, aim.lon], {
  radius: 6,
  color: "#f4f1ea",
  weight: 2,
  fillColor: "#243f34",
  fillOpacity: 1,
}).addTo(map);

function showZoom(index) {
  const level = zoomLevels()[index];
  map.setView(offset(aim.lat, aim.lon, aim.yaw, level.along), level.zoom);
  document.querySelectorAll(".zooms button").forEach((button) => {
    button.classList.toggle("on", Number(button.dataset.zoom) === index);
  });
}

document.querySelectorAll(".zooms button").forEach((button) => {
  button.addEventListener("click", () => showZoom(Number(button.dataset.zoom)));
});
showZoom(1);
requestAnimationFrame(() => map.invalidateSize());

async function loadAim() {
  // Relu à chaque visite plutôt que recopié dans ce fichier : le jour où la
  // caméra passera sur le toit du chalet, le calage changera et la carte doit
  // suivre sans qu'on y pense.
  try {
    const response = await fetch("data/scene.json", { cache: "no-store" });
    if (!response.ok) return;
    const pose = (await response.json()).pose || {};
    if (!pose.yaw || !pose.hfov) return;
    aim = {
      lat: pose.lat ?? aim.lat,
      lon: pose.lon ?? aim.lon,
      yaw: pose.yaw,
      hfov: pose.hfov,
      reach: pose.reach_m || aim.reach,
      rms: pose.rms || 0,
    };
  } catch (_) {
    /* Le cône reste sur le dernier calage connu. */
  }
  wedge.setLatLngs(viewWedge());
  axis.setLatLngs([[aim.lat, aim.lon], offset(aim.lat, aim.lon, aim.yaw, aim.reach)]);
  cameraMark.setLatLng([aim.lat, aim.lon]);
  showZoom(1);
  paintAim();
}

function paintAim() {
  const label = document.querySelector('[data-i18n="cameraText"]');
  if (!label) return;
  const spread = aim.rms ? ` ± ${(aim.rms * aim.hfov).toFixed(1)}°` : "";
  label.textContent = `${t("cameraFixed")} ${aim.yaw.toFixed(1)}°${spread} · ${t("cameraField")} ${aim.hfov.toFixed(1)}°`;
  label.removeAttribute("data-i18n");
}

function paintCamera() {
  cameraMark.unbindTooltip();
  cameraMark.bindTooltip(t("camera"), { permanent: true, direction: "top", offset: [0, -8] });
}

let sequenceFrames = [];
let sequenceIndex = 0;

const FOOT = 14;

function followSections() {
  /* Put a section on screen whole, and underline the one being read.

     Every section on this page but the log is shorter than a screenful, so
     landing on one has no business showing its first line and leaving its last
     below the fold. Clicking a heading centres the section in the room left
     under the bar; only the log, which is the whole history and has no bottom
     worth reaching, is aligned by its top.

     The underline follows whichever section fills most of the screen rather
     than whichever one last crossed a line, because once a section is centred
     its heading sits below that line and the previous one would keep winning. */
  const links = [...document.querySelectorAll(".onpage a")];
  const parts = links.map((link) => document.querySelector(link.getAttribute("href"))).filter(Boolean);
  if (!parts.length) return;
  const top = document.querySelector(".top");
  const waterline = () => (top?.offsetHeight || 78) + 8;

  const reveal = (part) => {
    const line = waterline();
    const room = window.innerHeight - line;
    const box = part.getBoundingClientRect();
    let y = window.scrollY + box.top - line;
    if (box.height < room) {
      // Settle on the foot of the section, not its head. What tells a reader
      // that a section is finished is seeing where it stops; landing on the
      // title leaves them to guess how much is still below.
      y = window.scrollY + box.bottom - window.innerHeight + FOOT;
      y = Math.min(y, window.scrollY + box.top - line);
    }
    window.scrollTo({ top: Math.max(Math.round(y), 0), behavior: "smooth" });
  };

  for (const link of links) {
    link.addEventListener("click", (hit) => {
      const part = document.querySelector(link.getAttribute("href"));
      if (!part) return;
      hit.preventDefault();
      reveal(part);
      history.replaceState(null, "", link.getAttribute("href"));
    });
  }

  const mark = () => {
    // Anything past the first screenful means the visit has started.
    const line = waterline();
    // Whichever section the waterline itself falls in. Counting visible pixels
    // instead handed the underline to the history the moment any of it showed,
    // because it is forty thousand pixels long and wins any such contest.
    let here = parts.find((part) => {
      const box = part.getBoundingClientRect();
      return box.top <= line && box.bottom > line;
    }) || parts.find((part) => part.getBoundingClientRect().top > line) || parts[0];
    if (window.innerHeight + window.scrollY >= document.body.scrollHeight - 4) here = parts[parts.length - 1];
    for (const link of links) {
      const on = link.getAttribute("href") === `#${here.id}`;
      if (on) link.setAttribute("aria-current", "true");
      else link.removeAttribute("aria-current");
    }
  };
  let waiting = false;
  addEventListener("scroll", () => {
    // Once per frame at most. Scrolling fires far faster than the page repaints.
    if (waiting) return;
    waiting = true;
    requestAnimationFrame(() => { waiting = false; mark(); });
  }, { passive: true });
  addEventListener("resize", mark);
  mark();
}

applyLang();
setInterval(tick, 1000);
loadWeather();
setInterval(loadWeather, 600000);
loadView();
setInterval(loadView, 60000);
loadAim();

function paintSequence() {
  const frame = sequenceFrames[sequenceIndex];
  if (!frame) return;
  document.querySelector("#seq-img").src = frame.thumb;
  document.querySelector("#seq-frame").href = `https://www.mapillary.com/app/?pKey=${encodeURIComponent(frame.id)}&focus=photo`;
  document.querySelector("#seq-count").textContent = `${sequenceIndex + 1} / ${sequenceFrames.length}`;
  const date = new Date(frame.captured_at).toLocaleDateString(locale(), { month: "long", year: "numeric" });
  document.querySelector("#sequence-meta").textContent = `Mapillary · ${date}`;
}

function stepSequence(delta) {
  if (!sequenceFrames.length) return;
  sequenceIndex = (sequenceIndex + delta + sequenceFrames.length) % sequenceFrames.length;
  paintSequence();
}

async function mly(pathname, params) {
  const url = new URL(pathname ? `https://graph.mapillary.com/${pathname}` : "https://graph.mapillary.com/");
  url.searchParams.set("access_token", "MLY|26158465847163536|0186af2cabb143cd46cccc023e7f0d81");
  Object.entries(params).forEach(([key, value]) => url.searchParams.set(key, value));
  const response = await fetch(url);
  if (!response.ok) throw new Error(String(response.status));
  return response.json();
}

async function loadSequence() {
  const pad = 0.02;
  const bbox = [CAMERA.lon - pad, CAMERA.lat - pad, CAMERA.lon + pad, CAMERA.lat + pad].join(",");
  const nearby = await mly("images", { fields: "id,computed_geometry,captured_at", bbox, limit: "200" });
  const near = (nearby.data || []).map((img) => {
    const coords = (img.computed_geometry || {}).coordinates;
    if (!coords || !img.captured_at) return null;
    return { id: img.id, captured_at: img.captured_at, lat: coords[1], lon: coords[0], dist: km(CAMERA, { lat: coords[1], lon: coords[0] }) };
  }).filter((img) => img && img.dist < 0.8);
  if (!near.length) return;
  const newest = Math.max(...near.map((img) => img.captured_at));
  let recent = near.filter((img) => newest - img.captured_at < 3 * 60 * 60 * 1000);
  recent.sort((a, b) => a.captured_at - b.captured_at);
  if (recent.length > 6) {
    const step = (recent.length - 1) / 5;
    recent = [0, 1, 2, 3, 4, 5].map((index) => recent[Math.round(index * step)]);
  }
  const details = await mly("", { fields: "id,thumb_1024_url,captured_at", ids: recent.map((img) => img.id).join(",") });
  sequenceFrames = recent.map((img) => {
    const shot = details[img.id];
    if (!shot || !shot.thumb_1024_url) return null;
    return { ...img, thumb: shot.thumb_1024_url, captured_at: shot.captured_at || img.captured_at };
  }).filter(Boolean);
  if (!sequenceFrames.length) return;
  const here = sequenceFrames.slice().sort((a, b) => a.dist - b.dist)[0];
  document.querySelector("#sequence-osm").href = `https://www.openstreetmap.org/?mlat=${here.lat}&mlon=${here.lon}#map=18/${here.lat}/${here.lon}`;
  sequenceIndex = 0;
  document.querySelector("#sequence").hidden = false;
  paintSequence();
}

document.querySelector("#seq-prev").addEventListener("click", () => stepSequence(-1));
document.querySelector("#seq-next").addEventListener("click", () => stepSequence(1));

load();
setInterval(load, 60000);
loadSequence();
followSections();
