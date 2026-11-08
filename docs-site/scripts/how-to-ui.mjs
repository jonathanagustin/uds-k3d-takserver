// Copyright 2026 uds-k3d-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

// Only generated main-channel guides use MDX. Repository and release sources
// remain Markdown, including their shell commands and warning callouts.
export function howToSteps(markdown) {
  const section = /^## Steps\r?\n([\s\S]*?)(?=^## |$(?![\s\S]))/m.exec(markdown);
  if (!section || !/^\d+\. /m.test(section[1])) return null;
  // MDX interprets braces and angle brackets in prose. Protect literals while
  // leaving fenced commands, inline code, and Markdown blockquotes untouched.
  const safe = markdown.split(/(```[\s\S]*?```|~~~[\s\S]*?~~~|`[^`\n]*`|<!--[\s\S]*?-->)/g)
    .map((part, index) => index % 2
      ? (part.startsWith('<!--') ? `{/*${part.slice(4, -3).replaceAll('*/', '* /')}*/}` : part)
      : part
      .replace(/\{/g, '&#123;').replace(/\}/g, '&#125;')
      .replace(/</g, '&lt;'))
    .join('');
  return "import { Steps } from '@astrojs/starlight/components';\n\n" + safe.replace(
    /(^## Steps\r?\n)([\s\S]*?)(?=^## |$(?![\s\S]))/m,
    (_, heading, body) => `${heading}\n<Steps>\n${body.trim()}\n</Steps>\n\n`,
  );
}
