"""GitHub OAuth utilities for FastMCP."""

import os

from fastmcp.server.dependencies import get_access_token


def get_github_login() -> str:
	"""Return the authenticated user's GitHub handle, or 'anonymous' if not authenticated.

	Call this inside a tool function body to identify the caller.
	"""
	token = get_access_token()
	if token is None:
		return "anonymous"
	return (token.claims.get("login") or "anonymous").lower()


def build_github_auth():
	"""Build OAuth auth provider if GitHub credentials are configured.

	Returns None if any required env var (GITHUB_CLIENT_ID, GITHUB_CLIENT_SECRET,
	MCP_BASE_URL) is missing — the server then runs without authentication.
	"""
	client_id = os.getenv("GITHUB_CLIENT_ID")
	client_secret = os.getenv("GITHUB_CLIENT_SECRET")
	base_url = os.getenv("MCP_BASE_URL")

	if not (client_id and client_secret and base_url):
		return None

	from fastmcp.server.auth.providers.github import GitHubProvider, GitHubTokenVerifier

	allowed_users_raw = os.getenv("GITHUB_ALLOWED_USERS", "")
	allowed_users = {u.strip().lower() for u in allowed_users_raw.split(",") if u.strip()}

	provider = GitHubProvider(
		client_id=client_id,
		client_secret=client_secret,
		base_url=base_url,
	)

	if allowed_users:
		original_verifier = provider._token_validator  # noqa: SLF001

		class _AllowlistVerifier(GitHubTokenVerifier):
			async def verify_token(self, token: str):
				result = await original_verifier.verify_token(token)
				if result is None:
					return None
				login = (result.claims.get("login") or "").lower()
				if login not in allowed_users:
					return None
				return result

		provider._token_validator = _AllowlistVerifier()  # noqa: SLF001

	return provider
