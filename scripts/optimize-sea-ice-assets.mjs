#!/usr/bin/env node
/**
 * Generate transparent, lossless previews from the public sea-ice SVGs.
 *
 * Usage: node scripts/optimize-sea-ice-assets.mjs
 * Requires the project's installed Sharp dependency (provided by Astro).
 *
 * Render at 144 dpi, then crop to the existing #map viewBox (80 0 1040 840).
 * At this density, the 1200 x 1000 SVG becomes 2400 x 2000 pixels, so the
 * crop is (160, 0, 2080, 1680). Resize with Sharp's default Lanczos3 kernel
 * and encode lossless WebP. The public SVG originals remain untouched.
 * Reproducible with the same Sharp/libvips versions and source assets.
 */

import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { dirname, join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';
import sharp from 'sharp';

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const assets = join(root, 'public', 'research');
const widths = [640, 960, 1280];
const crop = { left: 160, top: 0, width: 2080, height: 1680 };
const sha256 = (bytes) => createHash('sha256').update(bytes).digest('hex');

console.log(`Sharp ${sharp.versions.sharp}; libvips ${sharp.versions.vips}`);

for (const stem of ['nares-fractures', 'nares-stress']) {
  const sourcePath = join(assets, `${stem}-48h.svg`);
  const sourceBytes = await readFile(sourcePath);
  const sourceHash = sha256(sourceBytes);
  const source = sharp(sourceBytes, { density: 144 });
  const metadata = await source.metadata();
  assert.equal(metadata.width, 2400, `${stem}: unexpected SVG width`);
  assert.equal(metadata.height, 2000, `${stem}: unexpected SVG height`);
  assert.equal(metadata.hasAlpha, true, `${stem}: missing source alpha`);

  for (const width of widths) {
    const destination = join(assets, `${stem}-display-${width}.webp`);
    await source.clone()
      .extract(crop)
      .resize({ width, kernel: sharp.kernel.lanczos3 })
      .webp({ lossless: true, effort: 5 })
      .toFile(destination);

    const output = sharp(destination);
    const delivered = await output.metadata();
    assert.equal(delivered.format, 'webp');
    assert.equal(delivered.width, width);
    assert.equal(delivered.height, Math.round(width * crop.height / crop.width));
    assert.equal(delivered.hasAlpha, true, `${destination}: missing alpha`);
    const alpha = (await output.stats()).channels[3];
    assert.equal(alpha.min, 0, `${destination}: missing transparent background`);
    assert.ok(alpha.max > 0, `${destination}: empty image`);

    const bytes = await readFile(destination);
    console.log(
      `${relative(root, destination)}: ${delivered.width} x ${delivered.height}, ` +
      `${bytes.length} bytes; alpha ${alpha.min}–${alpha.max}; SHA-256 ${sha256(bytes)}`,
    );
  }

  assert.equal(sha256(await readFile(sourcePath)), sourceHash, `${stem}: source changed`);
  console.log(`${relative(root, sourcePath)}: unchanged (${sourceHash})`);
}
