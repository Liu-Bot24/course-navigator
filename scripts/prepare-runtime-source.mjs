import { createHash } from "node:crypto";
import { promises as fs } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { execFile } from "node:child_process";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";

const rootDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const resourceDir = path.join(rootDir, "launcher", "src-tauri", "resources", "runtime-source");
const runtimeToolsDir = path.join(rootDir, "launcher", "src-tauri", "resources", "runtime-tools");
const manifestPath = path.join(resourceDir, ".course-navigator-runtime.json");
const execFileAsync = promisify(execFile);

const excludedDirs = new Set([
  ".git",
  ".internal-docs",
  ".venv",
  "node_modules",
  "dist",
  "Casks",
  "frontend/dist",
  "backend/tests",
  "launcher",
  ".worktrees",
  ".course-navigator",
  "course-navigator-workspace",
  "data",
  "downloads",
  "output",
  ".pytest_cache",
  ".ruff_cache",
  ".mypy_cache",
  "docs/superpowers",
]);

const excludedFiles = new Set([
  ".course-navigator-deps.json",
  ".gitignore",
  ".DS_Store",
  "DEVELOPMENT_LOG.md",
  "scripts/build-mac-dmg.sh",
  "scripts/prepare-mac-runtime-source.sh",
  "scripts/prepare-runtime-source.mjs",
]);

function normalize(relativePath) {
  return relativePath.split(path.sep).join("/");
}

function isExcluded(relativePath, isDirectory) {
  const rel = normalize(relativePath);
  const name = path.posix.basename(rel);
  if (!rel) {
    return false;
  }
  if (name === ".env.example") {
    return false;
  }
  if (name === ".env" || name.startsWith(".env.")) {
    return true;
  }
  if (name.startsWith("._")) {
    return true;
  }
  if (name === "__pycache__") {
    return true;
  }
  if (name.endsWith(".tsbuildinfo")) {
    return true;
  }
  if (rel.startsWith("frontend/src/") && name.includes(".test.")) {
    return true;
  }
  if (excludedFiles.has(rel)) {
    return true;
  }
  if (isDirectory && (excludedDirs.has(rel) || excludedDirs.has(name))) {
    return true;
  }
  for (const dir of excludedDirs) {
    if (rel.startsWith(`${dir}/`)) {
      return true;
    }
  }
  return false;
}

async function copyDir(source, target) {
  await fs.mkdir(target, { recursive: true });
  for (const entry of await fs.readdir(source, { withFileTypes: true })) {
    const sourcePath = path.join(source, entry.name);
    const relativePath = path.relative(rootDir, sourcePath);
    if (isExcluded(relativePath, entry.isDirectory())) {
      continue;
    }
    const targetPath = path.join(target, entry.name);
    if (entry.isDirectory()) {
      await copyDir(sourcePath, targetPath);
    } else if (entry.isSymbolicLink()) {
      const linkTarget = await fs.readlink(sourcePath);
      await fs.symlink(linkTarget, targetPath);
    } else if (entry.isFile()) {
      await fs.copyFile(sourcePath, targetPath);
    }
  }
}

async function collectFiles(dir) {
  const files = [];
  for (const entry of await fs.readdir(dir, { withFileTypes: true })) {
    const filePath = path.join(dir, entry.name);
    if (filePath === manifestPath) {
      continue;
    }
    if (entry.isDirectory()) {
      files.push(...(await collectFiles(filePath)));
    } else if (entry.isFile()) {
      files.push(filePath);
    }
  }
  return files;
}

async function sourceHash() {
  const files = await collectFiles(resourceDir);
  files.sort((left, right) => normalize(path.relative(resourceDir, left)).localeCompare(normalize(path.relative(resourceDir, right))));
  const hash = createHash("sha256");
  for (const file of files) {
    const relativePath = normalize(path.relative(resourceDir, file));
    hash.update(relativePath);
    hash.update("\0");
    hash.update(await fs.readFile(file));
    hash.update("\0");
  }
  return hash.digest("hex");
}

async function prepareRuntimeTools() {
  await fs.rm(runtimeToolsDir, { recursive: true, force: true });
  await fs.mkdir(runtimeToolsDir, { recursive: true });
  if (process.platform === "win32") {
    await prepareWindowsRuntimeTools();
  } else if (process.platform === "darwin") {
    await prepareMacRuntimeTools();
  }
  await fs.writeFile(path.join(runtimeToolsDir, ".gitkeep"), "");
}

async function prepareWindowsRuntimeTools() {
  const windowsDir = path.join(runtimeToolsDir, "windows");
  const tempDir = path.join(runtimeToolsDir, ".tmp");
  await fs.mkdir(windowsDir, { recursive: true });
  await fs.mkdir(tempDir, { recursive: true });

  const nodeVersion = process.env.COURSE_NAVIGATOR_WINDOWS_NODE_VERSION || (await latestNodeLtsVersion("win-x64-zip"));
  const nodeZip = path.join(tempDir, `node-${nodeVersion}-win-x64.zip`);
  const nodeUrl = `https://nodejs.org/dist/${nodeVersion}/node-${nodeVersion}-win-x64.zip`;
  await downloadFile(nodeUrl, nodeZip);
  const nodeExtractDir = path.join(tempDir, "node");
  await expandArchive(nodeZip, nodeExtractDir);
  await renameOnlyChildDirectory(nodeExtractDir, path.join(windowsDir, "node"), "Downloaded Node archive did not contain a directory");

  const uvZip = path.join(tempDir, "uv-x86_64-pc-windows-msvc.zip");
  await downloadFile(
    "https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip",
    uvZip,
  );
  await expandArchive(uvZip, path.join(windowsDir, "uv"));
  await prepareWindowsMediaTools(windowsDir, tempDir);
  await fs.rm(tempDir, { recursive: true, force: true });
}

async function prepareMacRuntimeTools() {
  const arch = macRuntimeArch();
  const macDir = path.join(runtimeToolsDir, `darwin-${arch}`);
  const tempDir = path.join(runtimeToolsDir, ".tmp");
  await fs.mkdir(macDir, { recursive: true });
  await fs.mkdir(tempDir, { recursive: true });

  const nodeVersion =
    process.env.COURSE_NAVIGATOR_MAC_NODE_VERSION ||
    (await latestNodeLtsVersion(`osx-${arch}-tar`));
  const nodeArchive = path.join(tempDir, `node-${nodeVersion}-darwin-${arch}.tar.gz`);
  const nodeUrl = `https://nodejs.org/dist/${nodeVersion}/node-${nodeVersion}-darwin-${arch}.tar.gz`;
  await downloadFile(nodeUrl, nodeArchive);
  const nodeExtractDir = path.join(tempDir, "node");
  await expandArchive(nodeArchive, nodeExtractDir);
  const nodeDir = path.join(macDir, "node");
  await renameOnlyChildDirectory(nodeExtractDir, nodeDir, "Downloaded Node archive did not contain a directory");
  await pruneMacNodeRuntime(nodeDir);
  await writeMacNodeCliWrappers(nodeDir);

  const uvArchiveName = macUvArchiveName(arch);
  const uvArchive = path.join(tempDir, uvArchiveName);
  await downloadFile(
    `https://github.com/astral-sh/uv/releases/latest/download/${uvArchiveName}`,
    uvArchive,
  );
  const uvExtractDir = path.join(tempDir, "uv");
  await expandArchive(uvArchive, uvExtractDir);
  await renameOnlyChildDirectory(uvExtractDir, path.join(macDir, "uv"), "Downloaded uv archive did not contain a directory");

  await prepareMacMediaTools(macDir, tempDir);
  await fs.rm(tempDir, { recursive: true, force: true });
}

function macRuntimeArch() {
  const requested = process.env.COURSE_NAVIGATOR_MAC_ARCH || process.arch;
  if (requested === "arm64" || requested === "x64") {
    return requested;
  }
  throw new Error(`Unsupported macOS runtime architecture: ${requested}`);
}

function macUvArchiveName(arch) {
  if (arch === "arm64") {
    return "uv-aarch64-apple-darwin.tar.gz";
  }
  if (arch === "x64") {
    return "uv-x86_64-apple-darwin.tar.gz";
  }
  throw new Error(`Unsupported macOS uv architecture: ${arch}`);
}

async function prepareMacMediaTools(macDir, tempDir) {
  const mediaDir = path.join(tempDir, "media");
  await fs.mkdir(mediaDir, { recursive: true });
  await execFileAsync("npm", [
    "install",
    "--prefix",
    mediaDir,
    "--no-save",
    "--omit=dev",
    "--no-audit",
    "--no-fund",
    "ffmpeg-ffprobe-static@6.1.2-rc.1",
  ]);

  const requireFromMedia = createRequire(path.join(mediaDir, "package.json"));
  const media = requireFromMedia("ffmpeg-ffprobe-static");
  const targetDir = path.join(macDir, "ffmpeg");
  await fs.mkdir(targetDir, { recursive: true });
  await copyExecutable(media.ffmpegPath, path.join(targetDir, "ffmpeg"));
  await copyExecutable(media.ffprobePath, path.join(targetDir, "ffprobe"));
}

async function pruneMacNodeRuntime(nodeDir) {
  for (const entry of ["CHANGELOG.md", "README.md", "include", "share"]) {
    await fs.rm(path.join(nodeDir, entry), { recursive: true, force: true });
  }
}

async function writeMacNodeCliWrappers(nodeDir) {
  const commands = [
    ["npm", "npm-cli.js"],
    ["npx", "npx-cli.js"],
  ];
  for (const [command, scriptName] of commands) {
    const wrapper = `#!/bin/sh
set -e
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
exec "$SCRIPT_DIR/node" "$SCRIPT_DIR/../lib/node_modules/npm/bin/${scriptName}" "$@"
    `;
    const target = path.join(nodeDir, "bin", command);
    await fs.rm(target, { force: true });
    await fs.writeFile(target, wrapper);
    await fs.chmod(target, 0o755);
  }
}

async function copyExecutable(source, target) {
  await fs.copyFile(source, target);
  await fs.chmod(target, 0o755);
}

async function prepareWindowsMediaTools(windowsDir, tempDir) {
  const ffmpegZip = path.join(tempDir, "ffmpeg-release-essentials.zip");
  const ffmpegUrl =
    process.env.COURSE_NAVIGATOR_WINDOWS_FFMPEG_URL ||
    "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip";
  await downloadFile(ffmpegUrl, ffmpegZip);
  const ffmpegExtractDir = path.join(tempDir, "ffmpeg");
  await expandArchive(ffmpegZip, ffmpegExtractDir);
  const binDir = await findDirectoryContaining(ffmpegExtractDir, ["ffmpeg.exe", "ffprobe.exe"]);
  const targetDir = path.join(windowsDir, "ffmpeg");
  await fs.mkdir(targetDir, { recursive: true });
  await fs.copyFile(path.join(binDir, "ffmpeg.exe"), path.join(targetDir, "ffmpeg.exe"));
  await fs.copyFile(path.join(binDir, "ffprobe.exe"), path.join(targetDir, "ffprobe.exe"));
}

async function findDirectoryContaining(dir, filenames) {
  const entries = await fs.readdir(dir, { withFileTypes: true });
  const names = new Set(entries.map((entry) => entry.name.toLowerCase()));
  if (filenames.every((filename) => names.has(filename.toLowerCase()))) {
    return dir;
  }
  for (const entry of entries) {
    if (entry.isDirectory()) {
      try {
        return await findDirectoryContaining(path.join(dir, entry.name), filenames);
      } catch (error) {
        if (error?.code !== "ENOENT") {
          throw error;
        }
      }
    }
  }
  const error = new Error(`Unable to find ${filenames.join(" and ")} in downloaded ffmpeg archive`);
  error.code = "ENOENT";
  throw error;
}

async function renameOnlyChildDirectory(source, target, errorMessage) {
  const topDir = (await fs.readdir(source, { withFileTypes: true })).find((entry) => entry.isDirectory());
  if (!topDir) {
    throw new Error(errorMessage);
  }
  await fs.rm(target, { recursive: true, force: true });
  await fs.rename(path.join(source, topDir.name), target);
}

async function latestNodeLtsVersion(requiredFile) {
  const response = await fetch("https://nodejs.org/dist/index.json");
  if (!response.ok) {
    throw new Error(`Unable to read Node release index: ${response.status}`);
  }
  const releases = await response.json();
  const release = releases.find((entry) => entry.lts && entry.files?.includes(requiredFile));
  if (!release?.version) {
    throw new Error(`Unable to find a Node LTS release with ${requiredFile}`);
  }
  return release.version;
}

async function downloadFile(url, target) {
  const maxAttempts = 3;
  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    try {
      console.log(`Downloading ${url} (${attempt}/${maxAttempts})`);
      const response = await fetch(url);
      if (!response.ok) {
        throw new Error(`status ${response.status}`);
      }
      await fs.writeFile(target, Buffer.from(await response.arrayBuffer()));
      return;
    } catch (error) {
      await fs.rm(target, { force: true });
      if (attempt === maxAttempts) {
        throw new Error(`Unable to download ${url}: ${error.message}`);
      }
      await new Promise((resolve) => setTimeout(resolve, attempt * 1000));
    }
  }
}

async function expandArchive(zipPath, destination) {
  await fs.rm(destination, { recursive: true, force: true });
  await fs.mkdir(destination, { recursive: true });
  if (process.platform === "win32") {
    await execFileAsync("powershell", [
      "-NoProfile",
      "-ExecutionPolicy",
      "Bypass",
      "-Command",
      `Expand-Archive -LiteralPath ${powershellQuote(zipPath)} -DestinationPath ${powershellQuote(destination)} -Force`,
    ]);
  } else {
    await execFileAsync("tar", ["-xf", zipPath, "-C", destination]);
  }
}

function powershellQuote(value) {
  return `'${value.replace(/'/g, "''")}'`;
}

await fs.rm(resourceDir, { recursive: true, force: true });
await copyDir(rootDir, resourceDir);
await fs.writeFile(path.join(resourceDir, ".gitkeep"), "");
await fs.writeFile(
  manifestPath,
  `${JSON.stringify(
    {
      name: "course-navigator-runtime-source",
      sourceHash: await sourceHash(),
    },
    null,
    2,
  )}\n`,
);
await prepareRuntimeTools();

console.log(`Prepared runtime source at ${resourceDir}`);
console.log(`Prepared runtime tools at ${runtimeToolsDir}`);
