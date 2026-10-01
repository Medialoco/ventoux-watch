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
      const voulu = decodeURI(demande.url.split("?")[0]);
      const chemin = join(dossier, voulu.endsWith("/") ? voulu + "index.html" : voulu);
      try {
        const corps = await readFile(chemin);
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
    headless: true,
    args: ["--hide-scrollbars", "--enable-unsafe-swiftshader", "--no-sandbox"],
  });
  veille(navigateur);
  try {
    const page = await navigateur.newPage();
    await page.setViewport({ width: LARGEUR, height: HAUTEUR, deviceScaleFactor: 1 });
    await page.goto(`http://127.0.0.1:${port}/`, { waitUntil: "domcontentloaded", timeout: 60000 });
    await page.waitForSelector("#relief canvas", { timeout: 60000 });
    // La scène prend toute la fenêtre et le reste de la page disparaît : on
    // filme le modèle, pas la page qui le contient. La largeur est posée sur
    // « #relief » et non sur l'étage au-dessus, parce que c'est elle que le
    // rendu lit pour se dimensionner — il se taille toujours en seize-neuvièmes
    // de ce qu'on lui donne, ce qui tombe bien.
    await page.evaluate((l) => {
      const scene = document.getElementById("relief-stage") || document.getElementById("relief");
      document.body.prepend(scene);
      for (const noeud of [...document.body.children]) if (noeud !== scene) noeud.remove();
      Object.assign(document.body.style, { margin: "0", background: "#000", overflow: "hidden" });
      for (const bouton of scene.querySelectorAll("button")) bouton.style.display = "none";
      const hote = document.getElementById("relief");
      Object.assign(hote.style, { width: l + "px", maxWidth: "none", margin: "0" });
      window.dispatchEvent(new Event("resize"));
    }, LARGEUR);
    await new Promise((p) => setTimeout(p, 2500));
    const toile = await page.$("#relief canvas");

    const images = Math.round(secondes * fps);
    const milieu = HAUTEUR / 2;
    // Réveiller d'abord, tirer ensuite, en deux gestes séparés. La page laisse
    // les contrôles endormis pour ne pas voler la molette au lecteur, et le
    // clic qui les réveille leur arrive alors qu'ils n'écoutent pas encore :
    // tout glissement commencé dans ce même geste est perdu.
    await page.mouse.click(LARGEUR / 2, milieu);
    await new Promise((p) => setTimeout(p, 300));

    // Un balayage qui va et revient, et non un tour complet. Les contrôles
    // font tourner la caméra autour d'un point situé sept cents mètres devant
    // elle : passé le quart de tour, elle se retrouve sous la montagne, et on
    // filme des polygones flottant dans le ciel. C'est ce qu'a donné le
    // premier essai.
    //
    // Un aller-retour d'un seul côté, et pas un balayage symétrique. La caméra
    // tourne autour d'un point posé dans le vallon, en gardant son altitude de
    // mille trois cent quatre-vingt-dix mètres ; du côté du Ventoux le sol
    // monte à mille neuf cents, donc à quelques degrés seulement elle se
    // retrouve dans la montagne et filme le dessous du maillage, les sapins
    // pendus la tête en bas. C'est ce qu'ont donné les deux premiers essais.
    // De l'autre côté le terrain redescend et la vue reste dégagée.
    //
    // Un cosinus relevé, donc : il part de zéro, va jusqu'à l'écart voulu et
    // revient exactement à son point de départ — la boucle se referme sans
    // raccord — en ralentissant aux deux bouts au lieu de buter.
    const ECART = 105;
    const centre = LARGEUR / 2;
    await page.mouse.move(centre, milieu);
    await page.mouse.down();
    for (let i = 0; i < images; i += 1) {
      const avance = (1 - Math.cos((2 * Math.PI * i) / images)) / 2;
      await page.mouse.move(centre + ECART * avance, milieu, { steps: 1 });
      await toile.screenshot({ path: join(atelier, String(i).padStart(5, "0") + ".png") });
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

/* Fermer le navigateur même quand c'est le script qu'on arrête.
 *
 * Un Chrome sans tête n'a pas de fenêtre : lancé en arrière-plan puis
 * abandonné, il reste des heures en mémoire sans que rien ne le signale, et il
 * empêche d'ouvrir un Chrome normal. C'est arrivé — quatre profils temporaires
 * et deux cents mégaoctets oubliés dans /var/folders.
 *
 * Le « finally » plus haut ne suffit pas : il ne s'exécute que si le script
 * reprend la main. Sur un signal, il faut fermer soi-même.
 */
function veille(navigateur) {
  for (const signal of ["SIGINT", "SIGTERM", "SIGHUP"]) {
    process.once(signal, async () => {
      await navigateur.close().catch(() => {});
      process.exit(130);
    });
  }
}

filme(options(process.argv.slice(2))).catch((souci) => {
  console.error(souci.message);
  process.exit(1);
});
