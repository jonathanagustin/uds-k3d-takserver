# Review rules for main

This is a runbook for the repository owner. It has not been applied. Ruleset `25580922` is unchanged. Run it only after the dependency-pin pull request is on `main`, and only if you want the stricter review. It does not add collaborators or change accounts.

GitHub's rule reference: [Available rules for rulesets](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets). The API is [REST API endpoints for rules](https://docs.github.com/en/rest/repos/rules) (`X-GitHub-Api-Version: 2026-03-10`). Reviews: [Approving a pull request with required reviews](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/reviewing-changes-in-pull-requests/approving-a-pull-request-with-required-reviews).

## What is on main today

Read on 2026-11-06 from `GET /repos/jonathanagustin/uds-k3d-takserver/rulesets/25580922`.

The ruleset is named `main`, id `25580922`, enforcement `active`, target `branch`, and it includes `~DEFAULT_BRANCH`. One ruleset is configured on the repository.

The pull request rule requires a pull request. Approving reviews required: `0`. Code owner review: off. Approval of the most recent push: off. Dismiss stale approvals when new commits are pushed: already on. Conversation resolution: on. Allowed merges: squash and rebase. The unattributed-Copilot extra approval is off. The required-reviewers list is empty.

Status checks are `hk`, `Analyze (actions)`, `Analyze (javascript-typescript)`, and `dependency-review`, each with `integration_id` `15368` (GitHub Actions). The branch does not have to be up to date with the base (`strict_required_status_checks_policy` is false). Deletion and force-push are blocked.

That read did not include `bypass_actors`. GitHub returns the bypass list only to a caller who can edit the ruleset. The recorded bypass is the repository admin, mode `pull_request`: an admin can skip the pull request requirements. `current_user_can_bypass` on that read was `never`.

A classic branch-protection read of `main` returned HTTP 403 to the token used for this check. This runbook updates the ruleset. It does not call the branch-protection API.

## Choices to send

Keep the pull request rule, the four checks, deletion block, force-push block, squash and rebase, conversation resolution, and stale-review dismissal. Change only the following.

| Choice | Send |
| --- | --- |
| One human approval | `required_approving_review_count` `1` |
| Dismiss stale approvals | `dismiss_stale_reviews_on_push` `true` (already on) |
| Approval after the latest push | `require_last_push_approval` `true`, if the API accepts it |
| Admins follow the rules | `bypass_actors` `[]` |
| Branch matches the latest base | `strict_required_status_checks_policy` `true` |
| Code owners | `require_code_owner_review` `false` until the step below |
| Named reviewers | `required_reviewers` `[]` |

Leave `require_extra_approval_for_unattributed_changes` false. That field is a Copilot preview setting, and it is false today.

## Who can approve

GitHub's review docs say pull request authors cannot approve their own pull requests, and a GitHub Copilot review does not count toward required approvals. The approving review has to come from a different person with write access.

`require_last_push_approval` means the most recent reviewable push must be approved by someone other than the person who pushed it. The approval has to be submitted after that push. An earlier approval does not cover a later push. The same reviewer can approve again after the push.

With stale-review dismissal also on, a new push drops existing approvals. The other person then approves again, after that push. Updating the branch from `main` changes the diff and can dismiss the approval the same way. Your own approval still does not count.

If the PUT responds `422` and the message names `require_last_push_approval`, this account did not accept that field. Send the same body with that field `false`. The approval count, the empty bypass list, and the up-to-date check can still go on. Read the error once. Do not keep retrying.

## Code owners

[`CODEOWNERS`](../CODEOWNERS) lists only `@jonathanagustin`. Leave code owner review off. Turning it on with that file would ask the pull request author to approve their own change, which GitHub does not count.

Code owner review is optional. Use it only after `CODEOWNERS` names a second human account, a real person with write access, and that person is not the author of the pull request you need to merge. Write their GitHub login in `CODEOWNERS`. Do not list an app or a bot. Dependabot, Renovate, Copilot, and GitHub Actions are not that second person. Merge the `CODEOWNERS` change first. Only then set `require_code_owner_review` to `true` in a later update. Until then, send `false`.

## Save the ruleset before you change it

Use `gh auth login` as the repository owner, or a token that can administer this repository. Do not commit the token or the backup file. GitHub hides `bypass_actors` from a token that cannot edit the ruleset. If the saved JSON has no `bypass_actors` key, stop.

```bash
gh api \
  -H "Accept: application/vnd.github+json" \
  -H "X-GitHub-Api-Version: 2026-03-10" \
  repos/jonathanagustin/uds-k3d-takserver/rulesets/25580922 \
  > ruleset-25580922-backup.json
```

The same call with curl:

```bash
curl -fsSL \
  -H "Accept: application/vnd.github+json" \
  -H "Authorization: Bearer $GH_TOKEN" \
  -H "X-GitHub-Api-Version: 2026-03-10" \
  https://api.github.com/repos/jonathanagustin/uds-k3d-takserver/rulesets/25580922 \
  -o ruleset-25580922-backup.json
```

Read `bypass_actors` in that file. The admin entry should have `"bypass_mode": "pull_request"`. If any other actor is in the list, an empty bypass list removes that actor too. Stop and edit the list by hand in that case. The target of this runbook is an empty list, so admins are included.

## Apply

`PUT /repos/jonathanagustin/uds-k3d-takserver/rulesets/25580922` replaces this ruleset. It does not create another one. Write this to `ruleset-25580922-strict.json`.

```json
{
  "name": "main",
  "target": "branch",
  "enforcement": "active",
  "bypass_actors": [],
  "conditions": {
    "ref_name": {
      "include": ["~DEFAULT_BRANCH"],
      "exclude": []
    }
  },
  "rules": [
    { "type": "deletion" },
    { "type": "non_fast_forward" },
    {
      "type": "pull_request",
      "parameters": {
        "allowed_merge_methods": ["squash", "rebase"],
        "dismiss_stale_reviews_on_push": true,
        "require_code_owner_review": false,
        "require_extra_approval_for_unattributed_changes": false,
        "require_last_push_approval": true,
        "required_approving_review_count": 1,
        "required_review_thread_resolution": true,
        "required_reviewers": []
      }
    },
    {
      "type": "required_status_checks",
      "parameters": {
        "do_not_enforce_on_create": false,
        "strict_required_status_checks_policy": true,
        "required_status_checks": [
          { "context": "hk", "integration_id": 15368 },
          { "context": "Analyze (actions)", "integration_id": 15368 },
          { "context": "Analyze (javascript-typescript)", "integration_id": 15368 },
          { "context": "dependency-review", "integration_id": 15368 }
        ]
      }
    }
  ]
}
```

```bash
gh api --method PUT \
  -H "Accept: application/vnd.github+json" \
  -H "X-GitHub-Api-Version: 2026-03-10" \
  repos/jonathanagustin/uds-k3d-takserver/rulesets/25580922 \
  --input ruleset-25580922-strict.json
```

```bash
curl -fsSL -X PUT \
  -H "Accept: application/vnd.github+json" \
  -H "Authorization: Bearer $GH_TOKEN" \
  -H "X-GitHub-Api-Version: 2026-03-10" \
  https://api.github.com/repos/jonathanagustin/uds-k3d-takserver/rulesets/25580922 \
  --data-binary @ruleset-25580922-strict.json
```

If last-push approval is rejected, change only `"require_last_push_approval"` to `false` in that file and send the PUT once more.

Then GET the ruleset again. You want `required_approving_review_count` `1`, `bypass_actors` `[]`, `strict_required_status_checks_policy` `true`, and the same four checks. `require_last_push_approval` is `true` only when the PUT that set it was accepted. In the site UI this is Settings, Rules, Rulesets, `main`: one required approval, dismiss stale approvals, require approval of the most recent reviewable push, code owner review off, the four status checks, require branches to be up to date, and an empty bypass list.

## Restore the backup

Restore from `ruleset-25580922-backup.json`, the GET you saved before the change. That file is the full ruleset, including `bypass_actors`. Do not restore from the reference copy at the bottom of this page. That copy has no bypass list.

The update endpoint does not take the read-only fields. Strip them, then PUT.

```bash
jq 'del(._links, .id, .node_id, .source, .source_type, .created_at, .updated_at, .current_user_can_bypass)' \
  ruleset-25580922-backup.json > ruleset-25580922-restore.json

gh api --method PUT \
  -H "Accept: application/vnd.github+json" \
  -H "X-GitHub-Api-Version: 2026-03-10" \
  repos/jonathanagustin/uds-k3d-takserver/rulesets/25580922 \
  --input ruleset-25580922-restore.json
```

If PUT returns 422, the error names the field to remove. Remove that one field from `ruleset-25580922-restore.json` and send it once more. GET the ruleset and compare `rules` and `bypass_actors` to the backup.

## Reference copy from 2026-11-06

This is the GET body returned to a caller who could not see `bypass_actors`. It is a record of the rules. It is not the restore file.

```json
{
  "name": "main",
  "target": "branch",
  "enforcement": "active",
  "conditions": {
    "ref_name": {
      "include": ["~DEFAULT_BRANCH"],
      "exclude": []
    }
  },
  "rules": [
    { "type": "deletion" },
    { "type": "non_fast_forward" },
    {
      "type": "pull_request",
      "parameters": {
        "allowed_merge_methods": ["squash", "rebase"],
        "dismiss_stale_reviews_on_push": true,
        "require_code_owner_review": false,
        "require_extra_approval_for_unattributed_changes": false,
        "require_last_push_approval": false,
        "required_approving_review_count": 0,
        "required_review_thread_resolution": true,
        "required_reviewers": []
      }
    },
    {
      "type": "required_status_checks",
      "parameters": {
        "do_not_enforce_on_create": false,
        "strict_required_status_checks_policy": false,
        "required_status_checks": [
          { "context": "hk", "integration_id": 15368 },
          { "context": "Analyze (actions)", "integration_id": 15368 },
          { "context": "Analyze (javascript-typescript)", "integration_id": 15368 },
          { "context": "dependency-review", "integration_id": 15368 }
        ]
      }
    }
  ]
}
```
