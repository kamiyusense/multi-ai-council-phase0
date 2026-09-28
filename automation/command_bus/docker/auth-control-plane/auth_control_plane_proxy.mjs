import { lookup } from "node:dns/promises";
import { createServer } from "node:http";
import net from "node:net";
import { pathToFileURL } from "node:url";

export const ALLOWED_AUTH_HOST = "platform.claude.com";
export const ALLOWED_AUTH_AUTHORITY = `${ALLOWED_AUTH_HOST}:443`;
export const DENIED_MODEL_AUTHORITY = "api.anthropic.com:443";
export const PROXY_BIND = "0.0.0.0";
export const PROXY_PORT = 3128;

const blockedV4 = new net.BlockList();
for (const [subnet, prefix] of [
  ["0.0.0.0", 8], ["10.0.0.0", 8], ["100.64.0.0", 10], ["127.0.0.0", 8],
  ["169.254.0.0", 16], ["172.16.0.0", 12], ["192.0.0.0", 24],
  ["192.0.2.0", 24], ["192.88.99.0", 24], ["192.168.0.0", 16],
  ["198.18.0.0", 15], ["198.51.100.0", 24], ["203.0.113.0", 24],
  ["224.0.0.0", 4], ["240.0.0.0", 4],
]) blockedV4.addSubnet(subnet, prefix, "ipv4");

const blockedV6 = new net.BlockList();
for (const [subnet, prefix] of [
  ["::", 128], ["::1", 128], ["::ffff:0:0", 96], ["64:ff9b:1::", 48],
  ["100::", 64], ["2001:db8::", 32], ["2002::", 16], ["fc00::", 7],
  ["fe80::", 10], ["ff00::", 8],
]) blockedV6.addSubnet(subnet, prefix, "ipv6");

export function classifyConnectAuthority(authority) {
  if (typeof authority !== "string" || authority.length > 255
      || /[^\x21-\x7e]/.test(authority) || authority.includes("@")
      || authority.includes("/") || authority.includes("\\") || authority.includes("#")
      || authority.includes("?")) return "DENY_MALFORMED";
  if (authority === DENIED_MODEL_AUTHORITY) return "DENY_MODEL_ENDPOINT";
  if (authority === ALLOWED_AUTH_AUTHORITY) return "ALLOW_AUTH_HOST";
  return "DENY_NOT_ALLOWLISTED";
}

export function isPublicAddress(address, family = net.isIP(address)) {
  if (family === 4) return !blockedV4.check(address, "ipv4");
  if (family === 6) {
    const canonical = address.toLowerCase();
    return (canonical.startsWith("2") || canonical.startsWith("3"))
      && !blockedV6.check(address, "ipv6");
  }
  return false;
}

async function resolveAllowedAuthHost() {
  return lookup(ALLOWED_AUTH_HOST, { all: true, verbatim: true });
}

function connectResolvedAddress(record) {
  return new Promise((resolve, reject) => {
    const upstream = net.connect({ host: record.address, port: 443, family: record.family });
    const timeout = setTimeout(() => onError(new Error("connect timeout")), 10_000);
    timeout.unref();
    const onError = (error) => {
      clearTimeout(timeout);
      upstream.destroy();
      reject(error);
    };
    upstream.once("error", onError);
    upstream.once("connect", () => {
      clearTimeout(timeout);
      upstream.removeListener("error", onError);
      resolve(upstream);
    });
  });
}

function endWithStatus(socket, status, reason) {
  if (socket.destroyed) return;
  socket.end(`HTTP/1.1 ${status} ${reason}\r\nConnection: close\r\nContent-Length: 0\r\n\r\n`);
}

export function createAuthControlProxy({
  resolveHost = resolveAllowedAuthHost,
  connectAddress = connectResolvedAddress,
} = {}) {
  const server = createServer((_request, response) => {
    response.writeHead(405, { Connection: "close", "Content-Length": "0" });
    response.end();
  });

  server.on("connect", (request, client, head) => {
    if (classifyConnectAuthority(request.url) !== "ALLOW_AUTH_HOST") {
      endWithStatus(client, 403, "Forbidden");
      return;
    }
    if (head.length) {
      endWithStatus(client, 400, "Bad Request");
      return;
    }

    void (async () => {
      let upstream;
      try {
        const addresses = await resolveHost();
        const selected = Array.isArray(addresses) ? addresses[0] : undefined;
        if (!selected || !isPublicAddress(selected.address, selected.family)) {
          endWithStatus(client, 502, "Bad Gateway");
          return;
        }
        upstream = await connectAddress(selected);
        if (client.destroyed) {
          upstream.destroy();
          return;
        }
        client.write("HTTP/1.1 200 Connection Established\r\n\r\n");
        client.pipe(upstream);
        upstream.pipe(client);
        client.once("close", () => upstream.destroy());
        upstream.once("error", () => client.destroy());
      } catch {
        if (upstream) upstream.destroy();
        endWithStatus(client, 502, "Bad Gateway");
      }
    })();
  });

  server.on("clientError", (_error, socket) => endWithStatus(socket, 400, "Bad Request"));
  return server;
}

export function main() {
  const server = createAuthControlProxy();
  server.on("error", () => {
    process.stderr.write("auth control-plane proxy failed to start\n");
    process.exitCode = 1;
  });
  server.listen(PROXY_PORT, PROXY_BIND);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) main();
