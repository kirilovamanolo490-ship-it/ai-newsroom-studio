# Official brand asset library

This directory holds unchanged assets from first-party pages, official CDNs, official press materials, and one installed official app bundle. It contains no SimpleIcons marks or hand-drawn approximations.

Use `manifest.json` as the index. Each `path` is the intended public path under `/brand-assets/`; `file` is the local repository path. `source_url` identifies the page or installed application, `resource_url` identifies the downloaded file or bundle resource, and `sha256` is the exact file digest. Entries with `variants` provide contrast choices for different backgrounds. New cache records also include `kind`, `first_cached_at`, `last_validated_at`, `width`, and `height`.

Resolve a brand from another video or script with:

```sh
python3 tools/brand_assets.py list
python3 tools/brand_assets.py resolve DeepSeek
```

The JSON result includes `id`, `path`, `file`, and `cache_status`. A verified local SHA match returns `cache_hit` without a network request. An unavailable or invalid record returns `pending` unless both `--source-url` and `--source-page` are supplied. Only pass URLs already verified on a first-party source; the command does not discover or guess URLs. `--refresh` is explicit and writes a new immutable filename rather than replacing an existing asset.

A downloaded asset does not grant a general reuse license or imply affiliation or endorsement. Follow the usage notes and source terms before publishing. Tencent's newsroom says its media-library images and videos are for editorial use only. Cloudflare's trademark guide says logo use requires written permission except for specified web badges. OpenAI's brand guide says to use Blossom only as provided, preserve spacing, and not use Blossom as the primary branding; pair it with the wordmark when space allows.

## Background and size guidance

- OpenAI: use the black Blossom/wordmark on light backgrounds and the white variants on dark backgrounds. The OpenAI Developers lockup is specific to the developer site. Blossom is a compact symbol, not the primary company branding.
- Codex: the installed official `com.openai.codex` application resources include light and dark-color 1024×1024 app icons. Choose the variant with the right tile contrast. These are installed app icons, not press-kit logos.
- Qoder: the official documentation site publishes a black wordmark for light backgrounds and a white wordmark for dark backgrounds. The original Qoder homepage logo is also retained.
- Other larger source artwork: ChatGPT official app icon (1024×1024), Tencent corporate media-library logo (2162×889), Cloudflare press-kit logo (512×173), and ElevenLabs SVG. Tencent corporate is separate from Tencent Youtu.
- Small UI use only: Anthropic and Claude favicons, Doubao favicon, Nous favicon, StepFun favicon, and the Tencent Youtu Research GitHub organization avatar. The Youtu image is an organization avatar, not an approved logo.
- `deepseek`: unchanged 195×41.36 SVG from the DeepSeek-LLM repository under the official `deepseek-ai` GitHub organization. Suitable as a horizontal logo on light backgrounds (the SVG itself specifies the artwork); product use is editorial identification.
- `claude-code`: 254×28 SVG lockup from the Claude Code docs page header. It contains the shared Claude sunburst beside “Claude Code Docs”; catalogued as the official documentation identity, not as an independent Claude Code trademark. Use the full lockup for editorial identification on light backgrounds.
- `lingguang`: 512×512 PNG served as the official LingGuang homepage's Open Graph preview image. The official page's parsed DOM exposes this image and a favicon, but no standalone logo or higher-resolution mark; this item is page artwork for editorial use, not a confirmed logo or app icon.
- `nous-portal`: unchanged 360×180 identity artwork (a hand and globe) from the actual official Portal sidebar. This is site identity artwork, not a separately verified wordmark.
- `amazon`: unchanged 2000×1125 press-center corporate brand image showing the Amazon smile. The brand identifies the company discussed in the story; the original news attribution remains Variety.
- `gemini`: 512×512 JPEG from the Google Gemini App Store listing (Google LLC / `com.google.gemini`). This is the Gemini iOS app icon, not a general Google corporate logo.
- `grok`: 512×512 JPEG from the Grok App Store listing (xAI app, seller X Corp. / `ai.x.GrokApp`). This identifies the Grok iOS app; it is not a Grok Bot-specific mark.
- `underdog`: 512×512 PNG from the official Underdog website's `icon.png`, also used as the site's app icon. It depicts Underdog's dog character; classify it as a product app icon, not a standalone logo or the X account avatar.
- `qwen`: 280×280 PNG from the QwenLM GitHub organization's actual avatar. Use it only as a small organization avatar for editorial identification; it is not a standalone Qwen logo.
- `elonmusk`: 400×400 JPEG from the X profile image linked by the raw author record for the cited Elon Musk post. It identifies the personal account and is not a Grok or SpaceX product logo.
- `vidu`: 512×512 PNG exposed by the official Vidu website as its PWA icon and Open Graph preview. Use as an app icon; the website's separate `logo.svg` is a 64×64 site icon and is not promoted here as a full-size logo.
- `command-code`: 872×190 dark-foreground and 871×190 white-foreground transparent SVG wordmark variants from Command Code's official Brand Assets page. Choose the dark foreground for light backgrounds and white foreground for dark backgrounds; use both as supplied.
- `github`: official black Invertocat SVG from the ZIP linked by GitHub's official Brand Toolkit logo page. White mark and black/white Invertocat+wordmark lockups are retained as variants. For editorial news, the lockup is clearer; GitHub's guidance says not to imply affiliation or endorsement.
- Still pending: a standalone high-resolution LingGuang logo/app icon and standalone Nous Portal wordmark. The official site artwork is kept as artwork; it is not relabelled as an independent logo.
- No confirmed separate Claude wordmark or full-size logo was captured. Do not relabel Anthropic's company mark as a Claude logo.

See `contact-sheet.html` for an offline visual index. `research/evidence/brand-assets/` contains source page and usage evidence. All original assets remain unchanged except the Anthropic mark, whose exact inline SVG geometry was extracted from the official homepage navigation.

## Production sync

```sh
research/.venv/bin/python tools/brand_assets.py sync --report research/evidence/2026-10-11/report.json
```

Sync checks all master files and variants before copying, reuses identical public files, retains provenance and dimensions, and adds newly cached main entries to the report library. The production command calls it automatically before preparing video props. `cache-sync-receipt.json` records copied/reused files and pending IDs. Source URLs are only used when explicitly adding a previously verified official file; normal rendering never downloads logos.
