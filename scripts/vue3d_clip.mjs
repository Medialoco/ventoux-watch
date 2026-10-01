/* A turn around the 3D model, filmed once here so the Pi can play it.
 *
 * The scene on the site is WebGL. The machine that holds the stream has no
 * graphics chip worth the name and no spare degrees, so it cannot draw it
 * sixteen times a second while it is already encoding video. It does not have
 * to: the model does not change from one hour to the next. One slow turn,
 * filmed on a laptop, loops cleanly and costs the Pi a small decode.
 *
 * The turn is driven by dragging the canvas, not by reaching into the page:
 * the stream films the scene the way a visitor sees it, so if the site ever
 * changes the film follows without anyone remembering to update it here.
 *
 *   node scripts/vue3d_clip.mjs [--secondes 40] [--fps 15] [--sortie data/vue3d.mp4]
 */
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { spawn } from "node:child_process";
import { tmpdir } from "node:os";
import { join, extname, resolve } from "node:path";
import puppeteer from "puppeteer-core";

const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const RACINE = resolve(new URL("..", import.meta.url).pathname);
const LARGEUR = 1280;
const HAUTEUR = 720;
const TYPES = { ".html": "text/html", ".js": "text/javascript", ".json": "application/json",
                ".css": "text/css", ".jpg": "image/jpeg", ".png": "image/png" };

function options(argv) {
  const dit = {};
  for (let i = 0; i < argv.length; i += 2) dit[argv[i].replace(/^--/, "")] = argv[i + 1];
  return { secondes: Number(dit.secondes ?? 40), fps: Number(dit.fps ?? 15),
           sortie: dit.sortie ?? "data/vue3d.mp4" };
}

function sert(dossier) {
  return new Promise((pret) => {
    const serveur = createServer(async (demande, reponse) => {
      const chemin = join(dossier, decodeURI(demande.url.split("?")[0]));
      try {
        const corps = await readFile(chemin.endsWith("/") ? join(chemin, "index.html") : chemin);
        reponse.writeHead(200, { "content-type": TYPES[extname(chemin)] ?? "application/octet-stream" });
        reponse.end(corps);
      } catch { reponse.writeHead(404); reponse.end(); }
    });
    serveur.listen(0, "127.0.0.1", () => pret(serveur));
  });
}

async function filme({ secondes, fps, sortie }) {
  const serveur = await sert(join(RACINE, "_site"));
  const port = serveur.address().port;
  const atelier = await mkdtemp(join(tmpdir(), "vue3d-"));
  const navigateur = await puppeteer.launch({
    executablePath: CHROME,
    // « new » et non l'ancien sans tête : seul celui-ci a un WebGL complet, et
    // sans lui la page se rabat sur rien et la scène reste noire.
    headless: "new",
    args: ["--enable-webgl", "--use-gl=angle", "--hide-scrollbars"],
  });
  try {
    const page = await navigateur.newPage();
    await page.setViewport({ width: LARGEUR, height: HAUTEUR, deviceScaleFactor: 1 });
    await page.goto(`http://127.0.0.1:${port}/`, { waitUntil: "networkidle2", timeout: 90000 });
    await page.waitForSelector("#relief canvas", { timeout: 60000 });
    // La scène prend toute la fenêtre et le reste de la page disparaît : on
    // filme le modèle, pas la page qui le contient.
    await page.evaluate((h) => {
      const scene = document.getElementById("relief-stage") || document.getElementById("relief");
      document.body.prepend(scene);
      for (const noeud of [...document.body.children]) if (noeud !== scene) noeud.remove();
      Object.assign(document.body.style, { margin: "0", background: "#000", overflow: "hidden" });
      Object.assign(scene.style, { position: "fixed", inset: "0", width: "100vw", height: h + "px" });
      for (const bouton of scene.querySelectorAll("button")) bouton.style.display = "none";
      window.dispatchEvent(new Event("resize"));
    }, HAUTEUR);
    await new Promise((p) => setTimeout(p, 2500));

    const images = Math.round(secondes * fps);
    const milieu = { x: LARGEUR / 2, y: HAUTEUR / 2 };
    // Réveiller les contrôles : la page les laisse endormis pour ne pas voler
    // la molette au lecteur, et un canevas endormi ne tourne pas.
    await page.mouse.click(milieu.x, milieu.y);
    await page.mouse.move(milieu.x, milieu.y);
    await page.mouse.down();
    // Un tour complet en « images » pas, donc la dernière image rejoint la
    // première : le film boucle sans raccord visible.
    const pas = LARGEUR / images;
    for (let i = 0; i < images; i += 1) {
      await page.mouse.move(milieu.x + pas, milieu.y, { steps: 1 });
      // La souris revient au centre sans bouton relâché n'aurait pas de sens ;
      // on garde donc le curseur qui dérive et on le ramène d'un cran.
      await page.mouse.move(milieu.x, milieu.y, { steps: 1 });
      await page.mouse.move(milieu.x + pas, milieu.y, { steps: 1 });
      await page.screenshot({ path: join(atelier, String(i).padStart(5, "0") + ".png") });
      if (i % 60 === 0) process.stdout.write(`  ${i}/${images}\n`);
    }
    await page.mouse.up();

    await new Promise((fini, rate) => {
      const ff = spawn("ffmpeg", ["-hide_banner", "-loglevel", "error", "-y",
        "-framerate", String(fps), "-i", join(atelier, "%05d.png"),
        "-c:v", "libx264", "-preset", "slow", "-crf", "20",
        "-pix_fmt", "yuv420p", join(RACINE, sortie)], { stdio: "inherit" });
      ff.on("exit", (code) => (code === 0 ? fini() : rate(new Error("ffmpeg " + code))));
    });
    console.log(`${sortie} · ${secondes} s · ${images} images`);
  } finally {
    await navigateur.close();
    serveur.close();
    await rm(atelier, { recursive: true, force: true });
  }
}

filme(options(process.argv.slice(2))).catch((souci) => {
  console.error(souci.message);
  process.exit(1);
});
