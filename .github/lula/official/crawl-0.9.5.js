// cli/commands/crawl.ts
import fs from "fs";
import { Octokit } from "@octokit/rest";
import { Command, Option } from "commander";
import { createHash } from "crypto";
var closingBody = `

---

<sub>**Tip:** Customize your compliance reviews with <a href="https://github.com/defenseunicorns/lula.git" class="Link--inTextBlock" target="_blank" rel="noopener noreferrer">Lula</a>.</sub>`;
var LULA_SIGNATURE = "<!-- LULA_SIGNATURE:v1 -->";
async function postFinding(params) {
  const { octokit, postMode, owner, repo, pull_number, body } = params;
  if (postMode === "comment") {
    await octokit.issues.createComment({
      owner,
      repo,
      issue_number: pull_number,
      body
    });
    return;
  }
  await octokit.pulls.createReview({
    owner,
    repo,
    pull_number,
    body,
    event: "REQUEST_CHANGES"
  });
}
function getPRContext() {
  const fallbackOwner = process.env.OWNER;
  const fallbackRepo = process.env.REPO;
  const fallbackNumber = process.env.PULL_NUMBER;
  if (fallbackOwner && fallbackRepo && fallbackNumber) {
    return {
      owner: fallbackOwner,
      repo: fallbackRepo,
      pull_number: parseInt(fallbackNumber, 10)
    };
  }
  if (process.env.GITHUB_EVENT_PATH && process.env.GITHUB_REPOSITORY) {
    const event = JSON.parse(fs.readFileSync(process.env.GITHUB_EVENT_PATH, "utf8"));
    const [owner, repo] = process.env.GITHUB_REPOSITORY.split("/");
    const pull_number = event.pull_request?.number;
    if (!pull_number) throw new Error("PR number not found in GitHub event payload.");
    return { owner, repo, pull_number };
  }
  throw new Error("Set OWNER, REPO, and PULL_NUMBER in the environment for local use.");
}
async function fetchRawFileViaAPI({
  octokit,
  owner,
  repo,
  path,
  ref
}) {
  const res = await octokit.repos.getContent({
    owner,
    repo,
    path,
    ref,
    headers: {
      accept: "application/vnd.github.v3.raw"
    }
  });
  if (typeof res.data === "string") {
    return res.data;
  }
  if (typeof res.data === "object" && res.data !== null && "content" in res.data && typeof res.data.content === "string") {
    const { content } = res.data;
    return Buffer.from(content, "base64").toString("utf-8");
  }
  throw new Error("Unexpected GitHub API response shape");
}
function extractMapBlocks(content) {
  const lines = content.split("\n");
  const blocks = [];
  const stack = [];
  lines.forEach((line, idx) => {
    const start = line.match(/@lulaStart\s+([a-f0-9-]+)/);
    const end = line.match(/@lulaEnd\s+([a-f0-9-]+)/);
    if (start) {
      stack.push({ uuid: start[1], line: idx });
    } else if (end) {
      const last = stack.find((s) => s.uuid === end[1]);
      if (last) {
        blocks.push({ uuid: last.uuid, startLine: last.line, endLine: idx + 1 });
        stack.splice(stack.indexOf(last), 1);
      }
    }
  });
  return blocks;
}
function getChangedBlocks(oldText, newText) {
  const oldBlocks = extractMapBlocks(oldText);
  const newBlocks = extractMapBlocks(newText);
  const changed = [];
  const oldLines = oldText.split("\n");
  const newLines = newText.split("\n");
  const oldBlocksByUuid = /* @__PURE__ */ new Map();
  const newBlocksByUuid = /* @__PURE__ */ new Map();
  oldBlocks.forEach((block) => {
    if (!oldBlocksByUuid.has(block.uuid)) {
      oldBlocksByUuid.set(block.uuid, []);
    }
    oldBlocksByUuid.get(block.uuid).push(block);
  });
  newBlocks.forEach((block) => {
    if (!newBlocksByUuid.has(block.uuid)) {
      newBlocksByUuid.set(block.uuid, []);
    }
    newBlocksByUuid.get(block.uuid).push(block);
  });
  for (const [uuid, newUuidBlocks] of newBlocksByUuid) {
    const oldUuidBlocks = oldBlocksByUuid.get(uuid) || [];
    if (oldUuidBlocks.length === 0) continue;
    if (oldUuidBlocks.length !== newUuidBlocks.length) {
      const exactMatches = /* @__PURE__ */ new Set();
      const oldBlocksWithoutMatches = [];
      for (let oldIndex = 0; oldIndex < oldUuidBlocks.length; oldIndex++) {
        const oldBlock = oldUuidBlocks[oldIndex];
        const oldContent = extractBlockContent(oldLines, oldBlock.startLine, oldBlock.endLine);
        let foundMatch = false;
        for (let newIndex = 0; newIndex < newUuidBlocks.length; newIndex++) {
          if (exactMatches.has(newIndex)) continue;
          const newBlock = newUuidBlocks[newIndex];
          const newContent = extractBlockContent(newLines, newBlock.startLine, newBlock.endLine);
          if (oldContent === newContent) {
            exactMatches.add(newIndex);
            foundMatch = true;
            break;
          }
        }
        if (!foundMatch) {
          oldBlocksWithoutMatches.push(oldIndex);
        }
      }
      const usedNewBlocks = new Set(exactMatches);
      for (const oldIndex of oldBlocksWithoutMatches) {
        const oldBlock = oldUuidBlocks[oldIndex];
        const candidates = [];
        for (let newIndex = 0; newIndex < newUuidBlocks.length; newIndex++) {
          if (!usedNewBlocks.has(newIndex)) {
            candidates.push({ index: newIndex, block: newUuidBlocks[newIndex] });
          }
        }
        if (candidates.length > 0) {
          const closest = candidates.reduce((best, candidate) => {
            const bestDistance = Math.abs(oldBlock.startLine - best.block.startLine);
            const candidateDistance = Math.abs(oldBlock.startLine - candidate.block.startLine);
            return candidateDistance < bestDistance ? candidate : best;
          });
          changed.push(closest.block);
          usedNewBlocks.add(closest.index);
        }
      }
      continue;
    }
    const pairings = findOptimalPairings(oldUuidBlocks, newUuidBlocks, oldLines, newLines);
    for (const { oldBlock, newBlock } of pairings) {
      const oldContent = extractBlockContent(oldLines, oldBlock.startLine, oldBlock.endLine);
      const newContent = extractBlockContent(newLines, newBlock.startLine, newBlock.endLine);
      if (oldContent !== newContent) {
        changed.push(newBlock);
      }
    }
  }
  return changed;
}
function findOptimalPairings(oldBlocks, newBlocks, oldLines, newLines) {
  const pairings = [];
  const usedOldBlocks = /* @__PURE__ */ new Set();
  const usedNewBlocks = /* @__PURE__ */ new Set();
  const similarities = [];
  for (let oldIndex = 0; oldIndex < oldBlocks.length; oldIndex++) {
    for (let newIndex = 0; newIndex < newBlocks.length; newIndex++) {
      const oldBlock = oldBlocks[oldIndex];
      const newBlock = newBlocks[newIndex];
      const oldContent = extractBlockContent(oldLines, oldBlock.startLine, oldBlock.endLine);
      const newContent = extractBlockContent(newLines, newBlock.startLine, newBlock.endLine);
      const contentSimilarity = oldContent === newContent ? 1 : 0;
      const positionDistance = Math.abs(oldBlock.startLine - newBlock.startLine);
      const maxDistance = Math.max(oldBlocks.length, newBlocks.length) * 10;
      const positionSimilarity = 1 - Math.min(positionDistance / maxDistance, 1);
      const score = contentSimilarity * 0.8 + positionSimilarity * 0.2;
      similarities.push({ oldIndex, newIndex, score });
    }
  }
  similarities.sort((a, b) => b.score - a.score);
  for (const { oldIndex, newIndex } of similarities) {
    if (!usedOldBlocks.has(oldIndex) && !usedNewBlocks.has(newIndex)) {
      pairings.push({
        oldBlock: oldBlocks[oldIndex],
        newBlock: newBlocks[newIndex]
      });
      usedOldBlocks.add(oldIndex);
      usedNewBlocks.add(newIndex);
    }
  }
  return pairings;
}
function extractBlockContent(lines, startLine, endLine) {
  return lines.slice(startLine + 1, endLine - 1).join("\n");
}
function getRemovedBlocks(oldText, newText) {
  const oldBlocks = extractMapBlocks(oldText);
  const newBlocks = extractMapBlocks(newText);
  const removed = [];
  for (const oldBlock of oldBlocks) {
    const newMatch = newBlocks.find((b) => b.uuid === oldBlock.uuid);
    if (!newMatch) {
      removed.push(oldBlock);
    }
  }
  return removed;
}
function containsLulaAnnotations(text) {
  const lines = text.split("\n");
  return lines.some((line) => line.includes("@lulaStart") || line.includes("@lulaEnd"));
}
function createInitialCommentBody(filesCount) {
  return `${LULA_SIGNATURE}
## Lula Compliance Overview

Please review the changes to ensure they meet compliance standards.

### Reviewed Changes

Lula reviewed ${filesCount} files changed that affect compliance.

`;
}
async function analyzeDeletedFiles(context) {
  const { octokit, owner, repo, baseSha, files } = context;
  const deletedFilesWithAnnotations = [];
  for (const file of files) {
    if (file.status === "removed") {
      try {
        const oldText = await fetchRawFileViaAPI({
          octokit,
          owner,
          repo,
          path: file.filename,
          ref: baseSha
        });
        if (containsLulaAnnotations(oldText)) {
          deletedFilesWithAnnotations.push(file.filename);
        }
      } catch (err) {
        console.error(`Error checking deleted file ${file.filename}: ${err}`);
      }
    }
  }
  if (deletedFilesWithAnnotations.length === 0) {
    return { hasFindings: false, warningContent: "" };
  }
  let warningContent = `

**Compliance Warning: Files with Lula annotations were deleted**

`;
  warningContent += `The following files contained compliance annotations (\`@lulaStart\`/\`@lulaEnd\`) and were deleted in this PR. This may affect compliance coverage:

`;
  for (const filename of deletedFilesWithAnnotations) {
    warningContent += `- \`${filename}\`
`;
  }
  warningContent += `
Please review whether:
`;
  warningContent += `- The compliance coverage provided by these files is still needed
`;
  warningContent += `- Alternative compliance measures have been implemented
`;
  warningContent += `- The deletion is intentional and compliance-approved

`;
  warningContent += `---

`;
  return { hasFindings: true, warningContent };
}
function generateChangedBlocksContent(filename, changedBlocks, newText) {
  if (changedBlocks.length === 0) {
    return "";
  }
  console.log(`Commenting regarding \`${filename}\`.`);
  let content = `

---
| File | Lines Changed |
| ---- | ------------- |
`;
  for (const block of changedBlocks) {
    content += `| \`${filename}\` | \`${block.startLine + 1}\u2013${block.endLine}\` |
`;
  }
  content += `
`;
  for (const block of changedBlocks) {
    const newBlockText = newText.split("\n").slice(block.startLine, block.endLine).join("\n");
    const blockSha256 = createHash("sha256").update(newBlockText).digest("hex");
    content += `**UUID:** \`${block.uuid}\`
**sha256:** \`${blockSha256}\`

`;
  }
  return content;
}
function generateRemovedBlocksContent(filename, removedBlocks, oldText) {
  if (removedBlocks.length === 0) {
    return "";
  }
  console.log(`Found removed annotations in \`${filename}\`.`);
  let content = `

**Compliance Warning: Lula annotations were removed from \`${filename}\`**

`;
  content += `The following compliance annotation blocks were present in the original file but are missing in the updated version:

`;
  content += `| File | Original Lines | UUID |
`;
  content += `| ---- | -------------- | ---- |
`;
  for (const block of removedBlocks) {
    content += `| \`${filename}\` | \`${block.startLine + 1}\u2013${block.endLine}\` | \`${block.uuid}\` |
`;
  }
  content += `
`;
  for (const block of removedBlocks) {
    const oldBlockText = oldText.split("\n").slice(block.startLine, block.endLine).join("\n");
    const blockSha256 = createHash("sha256").update(oldBlockText).digest("hex");
    content += `**UUID:** \`${block.uuid}\`
**sha256:** \`${blockSha256}\`

`;
  }
  content += `Please review whether:
`;
  content += `- The removal of these compliance annotations is intentional
`;
  content += `- Alternative compliance measures have been implemented
`;
  content += `- The compliance coverage is still adequate

`;
  content += `---

`;
  return content;
}
async function analyzeModifiedFiles(context) {
  const { octokit, owner, repo, baseSha, headSha, files } = context;
  let changesContent = "";
  let hasFindings = false;
  for (const file of files) {
    if (file.status === "added" || file.status === "removed") continue;
    try {
      const oldPath = file.status === "renamed" && file.previous_filename ? file.previous_filename : file.filename;
      const newPath = file.filename;
      const [oldText, newText] = await Promise.all([
        fetchRawFileViaAPI({ octokit, owner, repo, path: oldPath, ref: baseSha }),
        fetchRawFileViaAPI({ octokit, owner, repo, path: newPath, ref: headSha })
      ]);
      const changedBlocks = getChangedBlocks(oldText, newText);
      const removedBlocks = getRemovedBlocks(oldText, newText);
      const hasActualComplianceChanges = changedBlocks.length > 0 || removedBlocks.length > 0;
      if (hasActualComplianceChanges) {
        hasFindings = true;
        if (changedBlocks.length > 0) {
          changesContent += generateChangedBlocksContent(file.filename, changedBlocks, newText);
        }
        if (removedBlocks.length > 0) {
          changesContent += generateRemovedBlocksContent(file.filename, removedBlocks, oldText);
        }
      } else {
        const oldBlocks = extractMapBlocks(oldText);
        const newBlocks = extractMapBlocks(newText);
        if (newBlocks.length > oldBlocks.length) {
          console.log(
            `Skipping ${file.filename}: only new Lula annotations added, no existing compliance content modified`
          );
        }
      }
    } catch (err) {
      console.error(`Error processing ${file.filename}: ${err}`);
    }
  }
  return { hasFindings, changesContent };
}
async function performComplianceAnalysis(context) {
  let commentBody = createInitialCommentBody(context.files.length);
  let hasFindings = false;
  const deletedAnalysis = await analyzeDeletedFiles(context);
  if (deletedAnalysis.hasFindings) {
    hasFindings = true;
    commentBody += deletedAnalysis.warningContent;
  }
  const modifiedAnalysis = await analyzeModifiedFiles(context);
  if (modifiedAnalysis.hasFindings) {
    hasFindings = true;
    commentBody += modifiedAnalysis.changesContent;
  }
  return { hasFindings, commentBody };
}
async function cleanupOldPosts(context, postMode) {
  const { octokit, owner, repo, pull_number } = context;
  if (postMode === "comment") {
    await deleteOldIssueComments({ octokit, owner, repo, pull_number });
  } else {
    await dismissOldReviews({ octokit, owner, repo, pull_number });
    await deleteOldReviewComments({ octokit, owner, repo, pull_number });
  }
}
function crawlCommand() {
  return new Command().command("crawl").description("Detect compliance-related changes between @lulaStart and @lulaEnd in PR files").addOption(
    new Option("--post-mode <mode>", "How to post findings").choices(["review", "comment"]).default("review")
  ).action(async (opts) => {
    const { owner, repo, pull_number } = getPRContext();
    console.log(`Analyzing PR #${pull_number} in ${owner}/${repo} for compliance changes...`);
    const octokit = new Octokit({ auth: process.env.GITHUB_TOKEN });
    const pr = await octokit.pulls.get({ owner, repo, pull_number });
    const prBranch = pr.data.head.ref;
    const baseSha = pr.data.base.sha;
    const headSha = pr.data.head.sha;
    const { data: files } = await octokit.pulls.listFiles({ owner, repo, pull_number });
    const context = {
      octokit,
      owner,
      repo,
      pull_number,
      prBranch,
      baseSha,
      headSha,
      files
    };
    const analysisResult = await performComplianceAnalysis(context);
    await cleanupOldPosts(context, opts.postMode);
    if (analysisResult.hasFindings) {
      const finalBody = analysisResult.commentBody + closingBody;
      await postFinding({
        octokit,
        postMode: opts.postMode,
        owner,
        repo,
        pull_number,
        body: finalBody
      });
      const header = `Posted (${opts.postMode})`;
      const underline = "-".repeat(header.length);
      console.log(`
${header}
${underline}

${finalBody}

`);
    }
  });
}
async function deleteOldIssueComments({
  octokit,
  owner,
  repo,
  pull_number
}) {
  let page = 1;
  while (true) {
    const { data: comments } = await octokit.issues.listComments({
      owner,
      repo,
      issue_number: pull_number,
      per_page: 100,
      page
    });
    if (!comments.length) break;
    for (const c of comments) {
      const hasSignature = (c.body ?? "").includes(LULA_SIGNATURE);
      if (hasSignature) {
        await octokit.issues.deleteComment({ owner, repo, comment_id: c.id });
        break;
      }
    }
    page++;
  }
}
async function deleteOldReviewComments({
  octokit,
  owner,
  repo,
  pull_number
}) {
  let page = 1;
  while (true) {
    const { data: reviewComments } = await octokit.pulls.listReviewComments({
      owner,
      repo,
      pull_number,
      per_page: 100,
      page
    });
    if (!reviewComments.length) break;
    for (const rc of reviewComments) {
      const hasSignature = (rc.body ?? "").includes(LULA_SIGNATURE);
      if (hasSignature) {
        await octokit.pulls.deleteReviewComment({ owner, repo, comment_id: rc.id });
        break;
      }
    }
    page++;
  }
}
async function dismissOldReviews({
  octokit,
  owner,
  repo,
  pull_number
}) {
  let page = 1;
  while (true) {
    const { data: reviews } = await octokit.pulls.listReviews({
      owner,
      repo,
      pull_number,
      per_page: 100,
      page
    });
    if (!reviews.length) break;
    for (const r of reviews) {
      const hasSignature = (r.body ?? "").includes(LULA_SIGNATURE);
      const isAlreadyDismissed = r.state === "DISMISSED";
      if (hasSignature && !isAlreadyDismissed) {
        await octokit.pulls.dismissReview({
          owner,
          repo,
          pull_number,
          review_id: r.id,
          message: "Superseded by a new Lula compliance review."
        });
        break;
      }
    }
    page++;
  }
}
export {
  LULA_SIGNATURE,
  analyzeDeletedFiles,
  analyzeModifiedFiles,
  cleanupOldPosts,
  containsLulaAnnotations,
  crawlCommand,
  createInitialCommentBody,
  deleteOldIssueComments,
  deleteOldReviewComments,
  dismissOldReviews,
  extractMapBlocks,
  fetchRawFileViaAPI,
  findOptimalPairings,
  generateChangedBlocksContent,
  generateRemovedBlocksContent,
  getChangedBlocks,
  getPRContext,
  getRemovedBlocks,
  performComplianceAnalysis,
  postFinding
};
