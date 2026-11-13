// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

const recordings = new Map([
  ['https://github.com/user-attachments/assets/7d727d39-b4f1-4251-b440-57c7799c51d1', 'demo-deploy.mp4'],
  ['https://github.com/user-attachments/assets/2773b517-9793-45b9-811b-147ce0671d69', 'demo-operate-and-trust.mp4'],
]);

export function embedDemoVideos(markdown, videos, assetBase = '/uds-takserver') {
  // A README line that is only a user-attachments URL is GitHub's inline
  // player. Known recordings map to their verified release copies; historical
  // pages can still identify the recording through their next download link.
  // A line that is only a poster linking to a demo release video (a chapter
  // clip on a doc page, written as [![alt](poster)](video) so GitHub shows
  // the poster) becomes a <video> with that poster.
  const lines = markdown.split('\n');
  return lines
    .map((line, index) => {
      const clip = line
        .trim()
        .match(/^\[!\[([^\]]*)\]\(([^)\s]+\.(?:jpg|png|webp))\)\]\(https:\/\/github\.com\/[^)\s]+\/releases\/download\/demo\/([\w.-]+\.mp4)\)$/);
      if (clip) {
        if (!videos.has(clip[3])) return line;
        const label = clip[1].replace(/"/g, '&quot;');
        return [
          `<video controls preload="none" playsinline width="1280" height="720" poster="${clip[2]}" aria-label="${label}">`,
          `  <source src="${assetBase}/demo/${clip[3]}" type="video/mp4" />`,
          `</video>`,
        ].join('\n');
      }
      if (!/^https:\/\/github\.com\/user-attachments\/assets\/\S+$/.test(line.trim())) return line;
      const next = lines.slice(index + 1).join('\n').match(/releases\/download\/demo\/([\w.-]+\.mp4)/);
      const name = recordings.get(line.trim()) ?? next?.[1];
      if (!name || !videos.has(name)) return line;
      const base = name.replace(/\.mp4$/, '');
      return [
        `<video controls preload="none" playsinline width="1280" height="720" poster="${assetBase}/demo/${base}.jpg">`,
        `  <source src="${assetBase}/demo/${name}" type="video/mp4" />`,
        `</video>`,
      ].join('\n');
    })
    .join('\n');
}

