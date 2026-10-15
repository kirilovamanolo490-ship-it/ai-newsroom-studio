#!/usr/bin/env node
// Parameterized, local-only QA for one reviewed morning/evening edition.
// Writes evidence only beneath research/report-redesign/qa/<date>/<edition>/parameterized.
// It never runs production, calls TTS, or edits production/verification state files.
const fs = require('node:fs/promises');
const fsSync = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { execFileSync } = require('node:child_process');

const ROOT = path.resolve(__dirname, '../..');
const args = Object.fromEntries(process.argv.slice(2).reduce((pairs, arg, i, all) => {
  if (arg.startsWith('--')) pairs.push([arg.slice(2), all[i + 1] && !all[i + 1].startsWith('--') ? all[i + 1] : true]);
  return pairs;
}, []));
const date = args.date;
const edition = args.edition;
if (!/^\d{4}-\d{2}-\d{2}$/.test(date || '') || !['morning', 'evening'].includes(edition)) {
  console.error('Usage: node research/report-redesign/verify-edition-qa.cjs --date YYYY-MM-DD --edition morning|evening [--base-url http://127.0.0.1:4311]');
  process.exit(2);
}
const out = path.join(ROOT, 'research/evidence', date, edition);
const qaDir = args['qa-dir'] ? path.resolve(String(args['qa-dir'])) : path.join(ROOT, 'research/report-redesign/qa', date, edition, 'parameterized');
const webOrigin = String(args['base-url'] || 'http://127.0.0.1:4311').replace(/\/$/, '');
const pageUrl = `${webOrigin}/${date}/${edition}/?video=v7#videos`;
const say = (ok, message) => { if (!ok) throw new Error(message); };
const sha = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const readJson = async p => JSON.parse(await fs.readFile(p, 'utf8'));
const fromEvidenceUrl = p => path.join(ROOT, 'research/evidence', String(p).replace(/^\/+/, ''));
const compositorTags = process.platform === 'darwin'
  ? [`darwin-${process.arch === 'arm64' ? 'arm64' : 'x64'}`]
  : process.platform === 'win32' ? ['win32-x64-msvc']
  : process.arch === 'arm64' ? ['linux-arm64-gnu', 'linux-arm64-musl'] : ['linux-x64-gnu', 'linux-x64-musl'];
const compositorDirs = compositorTags.map(tag => path.join(ROOT, 'prototypes/daily-brief-video/node_modules/@remotion/compositor-' + tag));
const resolveMediaTool = (name, envName) => {
  if (process.env[envName]) return process.env[envName];
  try {
    return execFileSync(process.platform === 'win32' ? 'where' : 'which', [name], { encoding: 'utf8' }).trim().split(/\r?\n/)[0];
  } catch {}
  for (const dir of compositorDirs) {
    const candidate = path.join(dir, name + (process.platform === 'win32' ? '.exe' : ''));
    if (fsSync.existsSync(candidate)) return candidate;
  }
  return null;
};
const ffprobe = resolveMediaTool('ffprobe', 'FFPROBE_PATH');
const ffmpeg = resolveMediaTool('ffmpeg', 'FFMPEG_PATH');
const mediaBin = path.dirname(ffprobe || ffmpeg || process.cwd());
if(process.platform==='darwin' && ffprobe && ffprobe.includes('@remotion')) process.env.DYLD_FALLBACK_LIBRARY_PATH=[path.dirname(ffprobe),process.env.DYLD_FALLBACK_LIBRARY_PATH].filter(Boolean).join(path.delimiter);
const result = {
  status: 'not_run', date, edition, page_url: pageUrl, checked_at: new Date().toISOString(),
  changed_files_scope: 'QA output directory only', checks: [], asset_hashes: [], screenshots: [],
  manual_visual_review: 'pending; screenshots must be opened and inspected before claiming visual verification',
};

async function hashAsset(label, file, expected) {
  const bytes = await fs.readFile(file);
  const actual = sha(bytes);
  say(!expected || actual === expected, `SHA256 mismatch: ${label}`);
  result.asset_hashes.push({ label, path: path.relative(ROOT, file), sha256: actual, expected_sha256: expected || null, passed: !expected || actual === expected, bytes: bytes.length });
  return bytes;
}

async function staticChecks() {
  say(Boolean(ffprobe), 'ffprobe not found; install FFmpeg on PATH or the platform Remotion compositor package');
  const reportPath = path.join(out, 'report.json');
  const ownPath = path.join(out, 'own-video.json');
  const episodePath = path.join(out, 'video-props.json');
  const productionPath = path.join(out, 'production-run.json');
  for (const p of [reportPath, ownPath, episodePath, productionPath]) say((await fs.stat(p)).isFile(), `Missing required edition artifact: ${path.relative(ROOT, p)}`);
  const [report, own, props, production] = await Promise.all([readJson(reportPath), readJson(ownPath), readJson(episodePath), readJson(productionPath)]);
  const episode = props.episode;
  say(report.date === date && report.edition === edition, 'Report date/edition mismatch');
  say(own.date === date && own.edition === edition, 'Own-video date/edition mismatch');
  say(episode.date === date && episode.edition === edition, 'Rendered episode date/edition mismatch');
  const python = path.join(ROOT, 'research/.venv/bin/python');
  const reportFingerprint = execFileSync(python, ['-c', [
    'import json, sys',
    'from pathlib import Path',
    'sys.path.insert(0, "tools")',
    'from edition_contract import report_fingerprint',
    'print(report_fingerprint(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8-sig"))))',
  ].join('; '), reportPath], { cwd: ROOT, encoding: 'utf8' }).trim();
  say(reportFingerprint.length === 64, 'Could not calculate the canonical report fingerprint');
  say(own.source_report_fingerprint === reportFingerprint, 'own-video fingerprint differs from the canonical report fingerprint');
  say(episode.source_report_fingerprint === reportFingerprint, 'video-props fingerprint differs from the canonical report fingerprint');
  say(production.source_report_fingerprint === reportFingerprint, 'production-run fingerprint differs from the canonical report fingerprint');
  result.source_report_fingerprint = reportFingerprint;
  say(own.revision === 7 && episode.presentation?.version === 7, 'Expected presentation/video revision V7');
  say(episode.voice?.provider === 'volcengine' && /Seed TTS 2\.0/.test(episode.voice?.model || '') && episode.voice?.resource_id === 'seed-tts-2.0', 'Expected Volcengine Seed TTS 2.0 voice metadata');
  say(episode.voice?.name === 'zh_female_vv_uranus_bigtts', 'Unexpected Seed Vivi voice');
  say(episode.scenes?.length > 0 && episode.scenes.every(s => s.captions?.length && s.audio), 'Scene audio or caption timing data missing');
  say(episode.scenes.every(s => /actual service word timestamps/i.test(s.caption_alignment?.method || '') && s.caption_alignment?.matching_ratio > 0.8), 'Captions are not aligned to actual Seed service timestamps');
  const voiceManifestPath = path.join(ROOT, episode.voice?.receipt_manifest || '');
  const voiceManifest = await readJson(voiceManifestPath);
  say(voiceManifest.model === 'Seed TTS 2.0' && voiceManifest.resource_id === 'seed-tts-2.0' && voiceManifest.speaker === 'zh_female_vv_uranus_bigtts', 'Seed TTS receipt manifest metadata mismatch');
  say(voiceManifest.scenes?.length === episode.scenes.length && voiceManifest.scenes.every(s => s.timestamps?.length > 0 && (s.audio || s.audio_path) && s.sha256), 'Seed receipt is missing scene audio, timestamps, or audio hashes');
  for (const scene of voiceManifest.scenes) {
    const audioPath = scene.audio || scene.audio_path;
    await hashAsset(`seed-voice:${scene.scene_id}`, path.isAbsolute(audioPath) ? audioPath : path.join(ROOT, audioPath), scene.sha256);
  }
  say(own.status !== 'verified' || own.verification, 'A verified own-video manifest must reference its verification receipt');

  const video = fromEvidenceUrl(own.path);
  const poster = fromEvidenceUrl(own.poster);
  const subtitles = fromEvidenceUrl(own.subtitles);
  const [videoBytes, posterBytes, subtitleText] = await Promise.all([
    hashAsset('rendered mp4', video, own.video_sha256), hashAsset('poster', poster, own.poster_sha256), fs.readFile(subtitles, 'utf8'),
  ]);
  const srtRows = subtitleText.trim().split(/\r?\n\s*\r?\n/).filter(Boolean);
  say(srtRows.length > 0 && srtRows.every(row => /^\d+\s*\r?\n\d{2}:\d{2}:\d{2},\d{3} --> \d{2}:\d{2}:\d{2},\d{3}\s*\r?\n[^\r\n]+/m.test(row)), 'SRT is empty or has malformed cue timestamps/text');
  result.subtitle_cues = srtRows.length;
  result.seed_voice_scenes = voiceManifest.scenes.length;
  result.video_sha256 = sha(videoBytes);
  result.poster_sha256 = sha(posterBytes);
  // Remotion's bundled macOS binary resolves its dylibs from its own directory.
  const probe = JSON.parse(execFileSync(ffprobe, ['-v', 'error', '-show_streams', '-show_format', '-of', 'json', video], { cwd: mediaBin, encoding: 'utf8' }));
  const vs = probe.streams.find(s => s.codec_type === 'video');
  const as = probe.streams.find(s => s.codec_type === 'audio');
  const ss = probe.streams.filter(s => s.codec_type === 'subtitle');
  const duration = Number(probe.format.duration);
  say(vs && vs.width === 1920 && vs.height === 1080, 'V7 MP4 must be 1920x1080');
  say(as && duration > 0 && Math.abs(duration - Number(own.duration_seconds)) < 0.5, 'MP4 audio stream/duration mismatch');
  say(posterBytes.readUInt32BE(16) === 1920 && posterBytes.readUInt32BE(20) === 1080, 'V7 poster must be 1920x1080');
  result.media = { width: vs.width, height: vs.height, fps: vs.r_frame_rate, duration_seconds: duration, audio_codec: as.codec_name, audio_sample_rate: as.sample_rate, audio_channels: as.channels, embedded_subtitle_streams: ss.length, sidecar_subtitle_cues: srtRows.length };

  const captureRows = report.stories.flatMap(s => (s.source_captures || []).map(c => ({ label: `capture:${s.id}:${c.label || ''}`, path: c.path, sha256: c.sha256 })));
  const originals = (report.image_assets || []).concat(report.video_assets || [], report.videos || []).filter(a => a && a.path && a.sha256);
  const seen = new Set();
  for (const a of captureRows.concat(originals.map(a => ({ label: `original:${a.type || 'media'}`, path: a.path, sha256: a.sha256 })))) {
    const key = `${a.path}:${a.sha256}`;
    if (seen.has(key)) continue; seen.add(key);
    await hashAsset(a.label, fromEvidenceUrl(a.path), a.sha256);
  }
  result.capture_count = captureRows.length;
  result.original_media_count = originals.length;
  result.checks.push('V7 report/episode/voice metadata, sidecar subtitle cues, MP4 audio/video dimensions and duration, poster dimensions, and capture/original-media SHA256');
  return { report, own, episode, video };
}

async function browserChecks(ctx) {
  const playwrightPath = process.env.PLAYWRIGHT_MODULE || require.resolve('playwright');
  const { chromium } = require(playwrightPath);
  const browser = await chromium.launch({ headless: true, ...(process.env.PLAYWRIGHT_EXECUTABLE ? { executablePath: process.env.PLAYWRIGHT_EXECUTABLE } : {}) });
  const errors = [];
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce' });
    page.on('pageerror', e => errors.push(e.message));
    page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
    await page.goto(pageUrl, { waitUntil: 'domcontentloaded' });
    if (await page.locator('.film-start').count()) { await page.locator('#own-video').evaluate(el=>{el.muted=true;}); await page.locator('.film-start').click(); }
    await page.locator('#own-video').waitFor({ state: 'visible' });
    const title = await page.title();
    say(title.includes(date) && title.includes(edition === 'morning' ? '早报' : '晚报'), 'Edition page title mismatch');
    const video = page.locator('#own-video');
    await video.evaluate(el => new Promise((resolve, reject) => {
      if (el.readyState >= 2) return resolve();
      el.addEventListener('loadeddata', resolve, { once: true });
      el.addEventListener('error', () => reject(new Error('HTML video failed to load')), { once: true });
      el.preload = 'auto'; el.load();
    }));
    // Mute only in the automated browser to satisfy autoplay policy; ffprobe
    // separately confirms that the delivered MP4 contains its audio stream.
    await video.evaluate(el => { el.muted = true; return el.play(); });
    await page.waitForTimeout(700);
    result.browser_playback = await video.evaluate(el => ({ src: new URL(el.currentSrc).pathname, width: el.videoWidth, height: el.videoHeight, duration: el.duration, ready_state: el.readyState, current_time: el.currentTime, paused: el.paused }));
    say(result.browser_playback.width === 1920 && result.browser_playback.height === 1080 && result.browser_playback.ready_state >= 2 && !result.browser_playback.paused && result.browser_playback.current_time > 0, 'Browser video playback did not advance');
    await page.screenshot({ path: path.join(qaDir, 'desktop.jpg'), fullPage: true }); result.screenshots.push('desktop.jpg');

    const chapterPicker = page.locator('.chapter-picker');
    if (await chapterPicker.count() && !(await chapterPicker.getAttribute('open'))) await chapterPicker.locator('summary').click();
    const chapters = page.locator('.chapters [data-seek]');
    const n = await chapters.count(); say(n > 0, 'No chapter links found');
    const mid = chapters.nth(Math.floor(n / 2));
    const expected = Number(await mid.getAttribute('data-seek'));
    const chapterTitle = (await mid.innerText()).trim();
    await mid.click();
    await page.waitForFunction(t => Math.abs(document.querySelector('#own-video').currentTime - t) < 1.2, expected);
    result.chapter_seek = { title: chapterTitle, expected_seconds: expected, observed_seconds: await video.evaluate(el => el.currentTime) };
    // currentTime updates before the decoder presents the target frame. Check visible media too.
    await page.waitForFunction(t => { const v=document.querySelector('#own-video'); return !v.seeking && v.readyState>=2 && v.currentTime>=t+0.8; }, expected);
    result.chapter_seek.presented_frame = await video.evaluate(el => new Promise(resolve => el.requestVideoFrameCallback((_now, metadata) => resolve({media_time: metadata.mediaTime, presented_frames: metadata.presentedFrames}))));
    await page.screenshot({ path: path.join(qaDir, 'chapter.jpg') }); result.screenshots.push('chapter.jpg');

    const firstImage = page.locator('.image-open:visible').first();
    say(await firstImage.count(), 'No source screenshot viewer trigger found');
    await firstImage.scrollIntoViewIfNeeded(); await firstImage.click();
    const dialog = page.locator('#image-viewer');
    await dialog.waitFor({ state: 'visible' });
    const viewer = await page.locator('#viewer-image').evaluate(async img => { await img.decode(); return { src: img.currentSrc, width: img.naturalWidth, height: img.naturalHeight, complete: img.complete }; });
    say(viewer.complete && viewer.width > 0 && viewer.height > 0, 'Screenshot viewer image did not load');
    result.screenshot_viewer = { open: true, ...viewer, source_url: await page.locator('#viewer-source').getAttribute('href') };
    await page.screenshot({ path: path.join(qaDir, 'screenshot-viewer.jpg') }); result.screenshots.push('screenshot-viewer.jpg');
    await page.locator('#viewer-close').click();

    const phone = await browser.newPage({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, deviceScaleFactor: 2 });
    phone.on('pageerror', e => errors.push(e.message));
    await phone.goto(pageUrl, { waitUntil: 'domcontentloaded' });
    if (await phone.locator('.film-start').count()) { await phone.locator('#own-video').evaluate(el=>{el.muted=true;}); await phone.locator('.film-start').click(); }
    await phone.locator('#own-video').waitFor({ state: 'visible' });
    result.mobile = await phone.evaluate(() => ({ viewport_width: innerWidth, viewport_height: innerHeight, page_width: document.documentElement.scrollWidth, player_width: document.querySelector('#own-video').getBoundingClientRect().width, player_height: document.querySelector('#own-video').getBoundingClientRect().height, horizontal_overflow: document.documentElement.scrollWidth > innerWidth }));
    say(!result.mobile.horizontal_overflow && result.mobile.player_width > 0 && result.mobile.player_height > 0, '390px mobile layout overflows or video is not visible');
    await phone.locator('.mobile-nav a[href="#videos"]').click();
    await phone.screenshot({ path: path.join(qaDir, 'mobile.jpg'), fullPage: true }); result.screenshots.push('mobile.jpg');
    result.runtime_errors = errors; say(errors.length === 0, `Browser runtime errors: ${errors.join(' | ')}`);
    result.checks.push('Rendered edition page plays the actual MP4; chapter seek works; source screenshot viewer opens and decodes; 390px phone layout has no horizontal overflow');
  } finally { await browser.close(); }
}

(async () => {
  await fs.mkdir(qaDir, { recursive: true });
  try {
    const ctx = await staticChecks();
    await browserChecks(ctx);
    result.status = 'automated_checks_passed_visual_review_pending';
  } catch (error) {
    result.status = 'failed'; result.failure = error.stack || error.message; process.exitCode = 1;
  }
  result.finished_at = new Date().toISOString();
  await fs.writeFile(path.join(qaDir, 'qa-result.json'), JSON.stringify(result, null, 2) + '\n');
  console.log(JSON.stringify(result, null, 2));
})();
