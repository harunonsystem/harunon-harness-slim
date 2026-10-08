#!/usr/bin/env python3
"""Inspect a literal comment command; execute only a revalidated frozen payload.

Owner policy is repository-source policy, never native/platform consent. All
writes use immutable GraphQL node IDs on the fixed GitHub endpoint. File/stdin
bodies, shell wrappers and unrecognized operations are outside this subset.
"""
import base64
import hashlib
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path


POLICY = Path(__file__).with_name("comment-owners.json")
REPLY = "mutation($thread:ID!,$body:String!){addPullRequestReviewThreadReply(input:{pullRequestReviewThreadId:$thread,body:$body}){comment{id}}}"
RESOLVE = "mutation($thread:ID!){resolveReviewThread(input:{threadId:$thread}){thread{id}}}"
COMMENT = "mutation($pr:ID!,$body:String!){addComment(input:{subjectId:$pr,body:$body}){commentEdge{node{id}}}}"
REVIEW = "mutation($pr:ID!,$body:String!){addPullRequestReview(input:{pullRequestId:$pr,event:COMMENT,body:$body}){pullRequestReview{id}}}"
THREAD_QUERY = "query($id:ID!){node(id:$id){... on PullRequestReviewThread{id isResolved viewerCanResolve repository{nameWithOwner url} pullRequest{number id headRefOid repository{nameWithOwner url}}}}}"
THREADS_QUERY = "query($id:ID!){node(id:$id){... on PullRequest{id reviewThreads(first:100){pageInfo{hasNextPage} nodes{id comments(first:100){pageInfo{hasNextPage} nodes{id databaseId}}}}}}}"


class Denied(ValueError):
    pass


def require(condition, reason):
    if not condition:
        raise Denied(reason)


def api(endpoint, fields=None):
    argv = ["gh", "api", "--hostname", "github.com", endpoint]
    for key, value in (fields or {}).items():
        argv += ["--raw-field", f"{key}={value}"]
    result = subprocess.run(argv, capture_output=True, text=True, timeout=30)
    require(result.returncode == 0, "GitHub lookup failed")
    data = json.loads(result.stdout)
    require(isinstance(data, dict) and not data.get("errors"), "GitHub lookup invalid")
    return data


def repository(value):
    policy = json.loads(POLICY.read_text())
    require(set(policy) == {"host", "owners"} and policy["host"] == "github.com" and
            isinstance(policy["owners"], list) and policy["owners"] and
            all(isinstance(owner, str) and re.fullmatch(r"[a-z0-9-]+", owner) for owner in policy["owners"]), "owner policy invalid")
    match = re.fullmatch(r"github\.com/([A-Za-z0-9-]+)/([A-Za-z0-9_.-]+)", value)
    require(match is not None, "explicit github.com/owner/repo required")
    owner, name = match.groups()
    require(owner.lower() in policy["owners"] and name not in (".", ".."), "owner not approved")
    return f"{owner.lower()}/{name.lower()}"


def parse(command):
    require(re.match(r"^\s*gh\s", command), "literal gh executable required")
    # Single quotes are literal in the supported shell subset. Expansion outside
    # them is rejected, rather than attempting to interpret arbitrary shell.
    exposed = re.sub(r"'[^']*'", "", command)
    require(not re.search(r"[$`\\\n\r]", exposed), "dynamic shell input unsupported")
    lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|()<>")
    lexer.whitespace_split = True
    lexer.commenters = ""
    tokens = list(lexer)
    require(not any(re.fullmatch(r"[;&|()<>]+", t) for t in tokens), "shell boundary unsupported")
    require(tokens[:1] == ["gh"], "standalone gh required")
    fields, options, positionals = {}, {}, []
    index = 3 if tokens[1:2] == ["pr"] else 2
    require(tokens[1:3] in (["pr", "comment"], ["pr", "review"]) or tokens[1:2] == ["api"], "operation unsupported")
    require(re.match(r"^\s*gh\s+(?:pr\s+(?:comment|review)|api)(?:\s|$)", command), "literal operation required")
    while index < len(tokens):
        token = tokens[index]
        if token == "--comment":
            require(token not in options, "duplicate option")
            options[token] = True
            index += 1
            continue
        names = {"-R": "repo", "--repo": "repo", "-b": "body", "--body": "body",
                 "--hostname": "host", "-X": "method", "--method": "method"}
        if token in names or token in ("-f", "--raw-field"):
            require(index + 1 < len(tokens), "option value missing")
            value = tokens[index + 1]
            if token in ("-f", "--raw-field"):
                key, separator, value = value.partition("=")
                require(separator and key not in fields, "duplicate or invalid field")
                fields[key] = value
            else:
                key = names[token]
                require(key not in options, "duplicate option")
                options[key] = value
            index += 2
        else:
            require(not token.startswith("-"), "unknown option; file/stdin bodies unsupported")
            positionals.append(token)
            index += 1
    if tokens[1] == "pr":
        require(set(options) == ({"repo", "body", "--comment"} if tokens[2] == "review" else {"repo", "body"}) and not fields, "explicit repo and inline body required")
        require(len(positionals) == 1, "explicit PR required")
        repo, number, operation, body = repository(options["repo"]), positionals[0], tokens[2], options["body"]
        target = ""
    else:
        require(options.get("host") == "github.com" and set(options) <= {"host", "method"}, "canonical API host required")
        require(len(positionals) == 1 and options.get("method", "POST") == "POST", "single POST endpoint required")
        endpoint = positionals[0]
        if endpoint == "graphql":
            query = re.sub(r"\s+", "", fields.get("query", ""))
            require(query in (REPLY, RESOLVE), "GraphQL operation unsupported")
            expected = {"query", "repo", "pr", "thread"} | ({"body"} if query == REPLY else set())
            require(set(fields) == expected, "explicit GraphQL repo/PR/inline fields required")
            repo, number = repository(fields["repo"]), fields["pr"]
            operation, target, body = ("reply" if query == REPLY else "resolve"), fields["thread"], fields.get("body", "")
            require(re.fullmatch(r"[A-Za-z0-9_+=/-]+", target), "thread ID invalid")
        else:
            match = re.fullmatch(r"repos/([^/]+/[^/]+)/pulls/([1-9][0-9]*)/comments/([1-9][0-9]*)/replies", endpoint)
            require(match is not None and set(fields) == {"body"}, "REST operation unsupported")
            repo, number = repository("github.com/" + match[1]), match[2]
            operation, target, body = "rest-reply", match[3], fields["body"]
    require(re.fullmatch(r"[1-9][0-9]*", number), "positive PR number required")
    require(operation == "resolve" or body.strip(), "empty body unsupported")
    require("\x00" not in body, "body invalid")
    return {"repo": repo, "number": int(number), "operation": operation, "target": target, "body": body}


def comment_graphql(command):
    """Detect a possible write, not authority; inspect still parses everything."""
    tokens = shlex.split(command)
    for index in range(len(tokens) - 1):
        if tokens[index:index + 2] != ["gh", "api"]:
            continue
        tail, endpoint, fields, unknown = tokens[index + 2:], None, [], False
        method, has_fields = None, False
        i = 0
        while i < len(tail):
            token = tail[i]
            if token in ("-f", "--raw-field", "-F", "--field", "--input", "--hostname", "-X", "--method", "-H", "--header", "--jq", "--template"):
                if i + 1 >= len(tail):
                    return True
                if token == "--input" or token in ("-F", "--field") and tail[i + 1].startswith("query="):
                    unknown = True
                if token in ("-f", "--raw-field", "-F", "--field", "--input"):
                    has_fields = True
                if token in ("-f", "--raw-field"):
                    fields.append(tail[i + 1])
                if token in ("-X", "--method"):
                    method = tail[i + 1]
                i += 2
            elif token.startswith("-"):
                if token.startswith(("-f", "-F", "--field=", "--raw-field=", "--input=")):
                    has_fields = True
                    unknown = True
                if token.startswith("-f") and len(token) > 2:
                    fields.append(token[2:])
                if token.startswith("--raw-field="):
                    fields.append(token[len("--raw-field="):])
                if token.startswith("-X") and len(token) > 2:
                    method = token[2:]
                if token.startswith("--method="):
                    method = token[len("--method="):]
                if token not in ("--paginate", "--slurp", "--silent", "--include", "--verbose"):
                    unknown = True
                i += 1
            else:
                if endpoint is None and (token.lstrip("/").startswith("repos/") or token.lstrip("/") == "graphql"):
                    endpoint = token.lstrip("/")
                i += 1
        if endpoint and re.search(r"(^|/)comments?(/|\?|$)", endpoint) and (
                method is not None and method.upper() != "GET" or method is None and has_fields):
            return True
        if endpoint == "graphql" and (unknown or any(
                field.startswith("query=") and re.search(r"\bmutation\b", field, re.I) and
                re.search(r"comment|reviewthread|addPullRequestReview", field, re.I) for field in fields)):
            return True
    # Shell launchers are unsupported; don't let their quoting hide a mutation.
    if tokens[:2] != ["gh", "api"]:
        return bool(re.search(r"\bgh\s+api\b", command) and (
            re.search(r"\bgraphql\b", command) and re.search(r"\bmutation\b", command, re.I) and re.search(r"comment|reviewthread|addPullRequestReview", command, re.I) or
            re.search(r"/comments?(?:/|\s|$)", command) and re.search(r"-X\s*(?:POST|PUT|PATCH|DELETE)|--method[=\s]+(?:POST|PUT|PATCH|DELETE)|(?:-f|-F|--field|--raw-field|--input)", command)))
    return False


def resolve(payload):
    repo, number = payload["repo"], payload["number"]
    repository("github.com/" + repo)
    identity = api("repos/" + repo)
    require(identity.get("full_name", "").lower() == repo and identity.get("html_url", "").lower() == "https://github.com/" + repo, "repository redirected or changed")
    require(type(identity.get("id")) is int, "repository identity missing")
    pr = api(f"repos/{repo}/pulls/{number}")
    require(pr.get("number") == number and pr.get("base", {}).get("repo", {}).get("id") == identity["id"] and pr.get("base", {}).get("repo", {}).get("full_name", "").lower() == repo, "PR repository mismatch")
    require(pr.get("url", "").lower() == f"https://api.github.com/repos/{repo}/pulls/{number}" and pr.get("html_url", "").lower() == f"https://github.com/{repo}/pull/{number}", "PR destination mismatch")
    require(isinstance(pr.get("node_id"), str) and re.fullmatch(r"[0-9a-f]{40}", pr.get("head", {}).get("sha", "")), "PR identity/head missing")
    target = payload["target"]
    if payload["operation"] == "rest-reply":
        comment = api(f"repos/{repo}/pulls/comments/{target}")
        require(comment.get("id") == int(target) and comment.get("pull_request_url") == pr["url"], "review comment/PR mismatch")
        require(isinstance(comment.get("node_id"), str), "review comment node missing")
        data = api("graphql", {"query": THREADS_QUERY, "id": pr["node_id"]})["data"]["node"]
        require(data["id"] == pr["node_id"] and not data["reviewThreads"]["pageInfo"]["hasNextPage"], "thread pagination unsupported")
        targets = []
        for thread in data["reviewThreads"]["nodes"]:
            require(not thread["comments"]["pageInfo"]["hasNextPage"], "comment pagination unsupported")
            if any(c.get("databaseId") == int(target) and c.get("id") == comment.get("node_id") for c in thread["comments"]["nodes"]):
                targets.append(thread["id"])
        require(len(targets) == 1, "review thread ambiguous or unavailable")
        target = targets[0]
    if payload["operation"] in ("reply", "rest-reply", "resolve"):
        node = api("graphql", {"query": THREAD_QUERY, "id": target})["data"]["node"]
        expected_repo = {"nameWithOwner": identity["full_name"], "url": identity["html_url"]}
        require(node["id"] == target and node["repository"] == expected_repo and node["pullRequest"]["repository"] == expected_repo and node["pullRequest"]["number"] == number and node["pullRequest"]["id"] == pr["node_id"] and node["pullRequest"]["headRefOid"] == pr["head"]["sha"], "thread repository/PR/head mismatch")
    if payload["operation"] == "resolve":
        require(node.get("isResolved") is False and node.get("viewerCanResolve") is True, "thread already resolved or cannot be resolved")
    return {"repositoryId": identity["id"], "pr": pr["node_id"], "head": pr["head"]["sha"], "thread": target,
            "bodySha256": hashlib.sha256(payload["body"].encode()).hexdigest()}


def main():
    if sys.argv[1:] == ["probe"]:
        return 0 if comment_graphql(sys.stdin.read()) else 3
    if sys.argv[1:] == ["inspect"]:
        payload = parse(sys.stdin.read())
        scope = resolve(payload)
        require(resolve(payload) == scope, "scope changed during lookup")
        capsule = base64.urlsafe_b64encode(json.dumps({"payload": payload, "scope": scope}, ensure_ascii=False, sort_keys=True).encode()).decode()
        command = shlex.join([sys.executable, str(Path(__file__).resolve()), "execute", capsule])
        # No native permissionDecision=allow: independent runtime refusals and
        # prompts still apply to the normal updatedInput protocol.
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
              "updatedInput": {"command": command}}}, ensure_ascii=False))
        return 0
    require(len(sys.argv) == 3 and sys.argv[1] == "execute", "inspect or frozen execute required")
    frozen = json.loads(base64.b64decode(sys.argv[2], altchars=b"-_", validate=True))
    payload, scope = frozen["payload"], frozen["scope"]
    require(set(payload) == {"repo", "number", "operation", "target", "body"} and payload["operation"] in ("comment", "review", "reply", "rest-reply", "resolve"), "frozen operation invalid")
    require(type(payload["number"]) is int and payload["number"] > 0 and isinstance(payload["body"], str) and
            (payload["body"] == "" if payload["operation"] == "resolve" else bool(payload["body"].strip())) and "\x00" not in payload["body"], "frozen payload invalid")
    require(resolve(payload) == scope and resolve(payload) == scope, "frozen scope stale")
    query = {"comment": COMMENT, "review": REVIEW, "resolve": RESOLVE}.get(payload["operation"], REPLY)
    key, target = ("pr", scope["pr"]) if payload["operation"] in ("comment", "review") else ("thread", scope["thread"])
    # No shell, file reopening, fallback, approval receipt, or mutation retry.
    argv = ["gh", "api", "--hostname", "github.com", "graphql", "--raw-field", "query=" + query,
            "--raw-field", key + "=" + target]
    if payload["operation"] != "resolve":
        argv += ["--raw-field", "body=" + payload["body"]]
    return subprocess.run(argv, timeout=30).returncode


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (Denied, KeyError, IndexError, AttributeError, TypeError, ValueError, OSError, subprocess.SubprocessError) as error:
        print("comment policy denied: " + (str(error) if isinstance(error, Denied) else "invalid or unavailable scope"), file=sys.stderr)
        sys.exit(2)
