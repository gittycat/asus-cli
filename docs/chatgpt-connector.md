# ChatGPT connector

asuswrt-chatgpt-connector runs the ASUSWRT MCP server on an Apple-silicon Mac
and connects it to ChatGPT through [OpenAI's Secure MCP
Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels).
It is intended for developer-mode testing while this project is under active
development and is not published in the MCP Registry.

    ChatGPT -> OpenAI tunnel -> tunnel-client -> asuswrt-mcp -> router

The Mac opens an outbound HTTPS connection to OpenAI. There is no inbound
listener and the router password stays on the Mac.

## Requirements

- Apple-silicon Mac running macOS 27 or later
- [uv](https://docs.astral.sh/uv/)
- An OpenAI tunnel ID and restricted runtime API key
- ChatGPT developer-mode access
- The Mac connected to the same network as the ASUS router

Create the tunnel in
[Platform tunnel settings](https://platform.openai.com/settings/organization/tunnels).
Associate it with the ChatGPT workspace in which the app will be created.
Create a restricted runtime key with **Tunnels Read + Use**. Do not use an
OpenAI admin key as the long-running connector key.

## Install from GitHub Releases

Download the archive and its .sha256 file from the matching project release:

    asuswrt-chatgpt-connector-v<VERSION>-macos27-arm64.tar.gz
    asuswrt-chatgpt-connector-v<VERSION>-macos27-arm64.tar.gz.sha256

Verify, unpack, and install:

    shasum -a 256 -c asuswrt-chatgpt-connector-v<VERSION>-macos27-arm64.tar.gz.sha256
    tar -xzf asuswrt-chatgpt-connector-v<VERSION>-macos27-arm64.tar.gz
    cd asuswrt-chatgpt-connector-v<VERSION>-macos27-arm64
    ./install.sh

The installer prompts for the router password, tunnel ID, and runtime key. The
key prompts are hidden. Existing router configuration at
~/.config/asuswrt/.env is reused.

The development archive is checksum-protected but is not yet notarized by this
project. If macOS blocks it, review the download and approve it under
**System Settings → Privacy & Security**.

Read-only is the default. To expose ordinary write tools:

    ./install.sh --permission writes

To additionally expose reboot and firmware upgrade:

    ./install.sh --permission dangerous

After changing the permission level, refresh the app's tool catalogue in
ChatGPT.

## Connect the app in ChatGPT

While the connector is running:

1. Open ChatGPT's plugin/app settings.
2. Create a developer-mode app.
3. Choose **Tunnel** under Connection.
4. Select the tunnel, or paste the tunnel ID printed by the installer.
5. Scan the tools and create the app.

Ask **what model is my ASUS router?** to verify the complete path.

## Manage it

    asuswrt-chatgpt-connector status
    asuswrt-chatgpt-connector doctor
    asuswrt-chatgpt-connector stop
    asuswrt-chatgpt-connector start
    asuswrt-chatgpt-connector restart

The local tunnel UI URL is written to:

    ~/Library/Application Support/asuswrt-chatgpt-connector/health-url

## Remove it

    asuswrt-chatgpt-connector uninstall

This removes the LaunchAgent, tunnel runtime key, tunnel profile, bundled
tunnel client, and connector logs. It keeps the router password and does not
delete the remote OpenAI tunnel. Add --router-config to remove the saved router
credentials too.

The connector relies on OpenAI's developer-mode and Secure MCP Tunnel product
availability. ChatGPT clients that do not expose custom apps cannot use it,
even when the local LaunchAgent is healthy.
