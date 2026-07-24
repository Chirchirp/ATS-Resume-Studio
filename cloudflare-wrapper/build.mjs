import { cp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const wrapperDirectory = path.dirname(fileURLToPath(import.meta.url));
const repositoryDirectory = path.resolve(wrapperDirectory, "..");
const sourceDirectory = path.resolve(wrapperDirectory, "src");
const checkOnly = process.argv.includes("--check");
const outputArgument = process.argv.find((argument) =>
  argument.startsWith("--output-directory=")
);
const configuredUrl = (process.env.STREAMLIT_APP_URL || "").trim();

function resolveOutputDirectory() {
  if (!outputArgument) {
    return path.resolve(wrapperDirectory, "dist");
  }

  const requestedDirectory = outputArgument.split("=", 2)[1]?.trim();
  if (!requestedDirectory) {
    throw new Error("--output-directory requires a relative directory path.");
  }

  const resolvedDirectory = path.resolve(repositoryDirectory, requestedDirectory);
  if (
    resolvedDirectory === repositoryDirectory ||
    !resolvedDirectory.startsWith(`${repositoryDirectory}${path.sep}`)
  ) {
    throw new Error("Output directory must stay inside the repository.");
  }
  return resolvedDirectory;
}

const outputDirectory = resolveOutputDirectory();

function validateStreamlitUrl(value) {
  if (!value) {
    throw new Error(
      "STREAMLIT_APP_URL is required. Set it to the public https://<app>.streamlit.app URL."
    );
  }

  let parsed;
  try {
    parsed = new URL(value);
  } catch {
    throw new Error("STREAMLIT_APP_URL must be a valid absolute URL.");
  }

  const validHostname =
    parsed.hostname === "streamlit.app" ||
    parsed.hostname.endsWith(".streamlit.app");

  if (
    parsed.protocol !== "https:" ||
    !validHostname ||
    parsed.username ||
    parsed.password ||
    parsed.hash
  ) {
    throw new Error(
      "STREAMLIT_APP_URL must be a public HTTPS URL on the streamlit.app domain."
    );
  }

  parsed.search = "";
  parsed.pathname = parsed.pathname.replace(/\/+$/, "") || "/";
  return parsed.toString();
}

async function validateSources() {
  const indexMarkup = await readFile(
    path.join(sourceDirectory, "index.html"),
    "utf8"
  );
  const requiredCopy = [
    "Starting ATS Resume Studio",
    "Application paused due to inactivity. click “Get this app back up.” Initial startup may take a short time.",
  ];

  for (const copy of requiredCopy) {
    if (!indexMarkup.includes(copy)) {
      throw new Error(`Missing required cold-boot copy: ${copy}`);
    }
  }
}

const streamlitUrl = validateStreamlitUrl(configuredUrl);
await validateSources();

if (checkOnly) {
  process.stdout.write(`Cloudflare wrapper configuration is valid for ${streamlitUrl}\n`);
  process.exit(0);
}

if (!outputDirectory.startsWith(`${repositoryDirectory}${path.sep}`)) {
  throw new Error("Refusing to write outside the repository.");
}

await rm(outputDirectory, { recursive: true, force: true });
await mkdir(outputDirectory, { recursive: true });
await cp(sourceDirectory, outputDirectory, { recursive: true });

const runtimeConfiguration = [
  "window.ATS_STUDIO_CONFIG = Object.freeze({",
  `  streamlitUrl: ${JSON.stringify(streamlitUrl)}`,
  "});",
  "",
].join("\n");

await writeFile(
  path.join(outputDirectory, "config.js"),
  runtimeConfiguration,
  "utf8"
);

process.stdout.write(`Built Cloudflare assets in ${outputDirectory}\n`);
