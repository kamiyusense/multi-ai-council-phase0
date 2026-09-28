import { lookup } from "node:dns/promises";
import { createServer } from "node:http";
import net from "node:net";
import { pathToFileURL } from "node:url";

export const ALLOWED_AUTH_HOST = "platform.claude.com";
export const ALLOWED_AUTH_AUTHORITY = `${ALLOWED_AUTH_HOST}:443`;
export const DENIED_MODEL_AUTHORITY = "api.anthropic.com:443";
export const PROXY_BIND = "0.0.0.0";
export const PROXY_PORT = 3128;
const MAX_CLIENT_HELLO_BYTES = 32 * 1024;
const CLIENT_HELLO_TIMEOUT_MS = 5_000;

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

function denyTls(reason) {
  return { status: "DENY", reason };
}

export function inspectTlsClientHello(buffer) {
  if (!Buffer.isBuffer(buffer) || buffer.length > MAX_CLIENT_HELLO_BYTES) {
    return denyTls("invalid_or_oversize_client_hello");
  }

  let offset = 0;
  const handshakeParts = [];
  let handshakeBytes = 0;
  let expectedHandshakeBytes = null;

  while (offset < buffer.length) {
    if (buffer.length - offset < 5) return { status: "NEED_MORE" };
    if (buffer[offset] !== 22) return denyTls("first_tls_record_is_not_handshake");
    const recordLength = buffer.readUInt16BE(offset + 3);
    if (recordLength === 0 || recordLength > 18_432) return denyTls("invalid_tls_record_length");
    if (buffer.length - offset - 5 < recordLength) return { status: "NEED_MORE" };

    const payload = buffer.subarray(offset + 5, offset + 5 + recordLength);
    handshakeParts.push(payload);
    handshakeBytes += payload.length;
    if (handshakeBytes > MAX_CLIENT_HELLO_BYTES) return denyTls("oversize_client_hello");

    const handshake = Buffer.concat(handshakeParts, handshakeBytes);
    if (handshake.length >= 4 && expectedHandshakeBytes === null) {
      if (handshake[0] !== 1) return denyTls("first_handshake_message_is_not_client_hello");
      expectedHandshakeBytes = 4 + handshake.readUIntBE(1, 3);
      if (expectedHandshakeBytes > MAX_CLIENT_HELLO_BYTES) return denyTls("oversize_client_hello");
    }
    if (expectedHandshakeBytes !== null && handshake.length >= expectedHandshakeBytes) {
      return inspectClientHelloBody(handshake.subarray(4, expectedHandshakeBytes));
    }
    offset += 5 + recordLength;
  }
  return { status: "NEED_MORE" };
}

function inspectClientHelloBody(body) {
  let offset = 0;
  const take = (count) => {
    if (!Number.isInteger(count) || count < 0 || offset + count > body.length) return null;
    const out = body.subarray(offset, offset + count);
    offset += count;
    return out;
  };
  const takeU8 = () => {
    const part = take(1);
    return part ? part[0] : null;
  };
  const takeU16 = () => {
    const part = take(2);
    return part ? part.readUInt16BE(0) : null;
  };

  if (!take(2) || !take(32)) return denyTls("truncated_client_hello");
  const sessionIdLength = takeU8();
  if (sessionIdLength === null || !take(sessionIdLength)) return denyTls("truncated_session_id");

  const cipherLength = takeU16();
  if (cipherLength === null || cipherLength < 2 || cipherLength % 2 !== 0 || !take(cipherLength)) {
    return denyTls("invalid_cipher_suites");
  }

  const compressionLength = takeU8();
  if (compressionLength === null || compressionLength < 1 || !take(compressionLength)) {
    return denyTls("invalid_compression_methods");
  }

  if (offset === body.length) return denyTls("missing_sni");
  const extensionsLength = takeU16();
  if (extensionsLength === null || extensionsLength !== body.length - offset) {
    return denyTls("invalid_extensions_length");
  }

  const extensionsEnd = offset + extensionsLength;
  let allowedSniCount = 0;
  while (offset < extensionsEnd) {
    const type = takeU16();
    const length = takeU16();
    if (type === null || length === null || offset + length > extensionsEnd) {
      return denyTls("truncated_extension");
    }
    const extension = take(length);
    if (type !== 0) continue;

    if (extension.length < 2) return denyTls("invalid_sni_extension");
    const listLength = extension.readUInt16BE(0);
    if (listLength !== extension.length - 2) return denyTls("invalid_sni_list_length");
    let nameOffset = 2;
    while (nameOffset < extension.length) {
      if (nameOffset + 3 > extension.length) return denyTls("truncated_sni_name");
      const nameType = extension[nameOffset];
      const nameLength = extension.readUInt16BE(nameOffset + 1);
      nameOffset += 3;
      if (nameOffset + nameLength > extension.length) return denyTls("truncated_sni_name");
      const rawName = extension.subarray(nameOffset, nameOffset + nameLength);
      nameOffset += nameLength;
      if (nameType !== 0) continue;
      if (rawName.length === 0 || /[^\x21-\x7e]/.test(rawName.toString("latin1"))) {
        return denyTls("invalid_sni_hostname");
      }
      const hostname = rawName.toString("ascii");
      if (hostname !== ALLOWED_AUTH_HOST) return denyTls("sni_not_allowlisted");
      allowedSniCount += 1;
    }
  }

  if (allowedSniCount !== 1) return denyTls("missing_or_ambiguous_sni");
  return { status: "ALLOW", sni: ALLOWED_AUTH_HOST };
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

function readValidatedClientHello(client) {
  return new Promise((resolve, reject) => {
    let buffered = Buffer.alloc(0);
    const timer = setTimeout(() => fail(new Error("client hello timeout")), CLIENT_HELLO_TIMEOUT_MS);
    timer.unref();

    const cleanup = () => {
      clearTimeout(timer);
      client.removeListener("data", onData);
      client.removeListener("close", onClose);
      client.removeListener("error", onError);
    };
    const fail = (error) => {
      cleanup();
      reject(error);
    };
    const onClose = () => fail(new Error("client closed before validated client hello"));
    const onError = () => fail(new Error("client error before validated client hello"));
    const onData = (chunk) => {
      client.pause?.();
      buffered = Buffer.concat([buffered, Buffer.from(chunk)]);
      const inspected = inspectTlsClientHello(buffered);
      if (inspected.status === "ALLOW") {
        cleanup();
        resolve(buffered);
        return;
      }
      if (inspected.status === "DENY" || buffered.length >= MAX_CLIENT_HELLO_BYTES) {
        fail(new Error("client hello rejected"));
        return;
      }
      client.resume?.();
    };

    client.on("data", onData);
    client.once("close", onClose);
    client.once("error", onError);
  });
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
      let tunnelAccepted = false;
      try {
        const addresses = await resolveHost();
        const selected = Array.isArray(addresses) ? addresses[0] : undefined;
        if (!selected || !isPublicAddress(selected.address, selected.family)) {
          endWithStatus(client, 502, "Bad Gateway");
          return;
        }

        client.write("HTTP/1.1 200 Connection Established\r\n\r\n");
        tunnelAccepted = true;
        const clientHello = await readValidatedClientHello(client);
        if (client.destroyed) return;

        upstream = await connectAddress(selected);
        if (client.destroyed) {
          upstream.destroy();
          return;
        }

        upstream.write(clientHello);
        client.pipe(upstream);
        upstream.pipe(client);
        client.once("close", () => upstream.destroy());
        upstream.once("error", () => client.destroy());
        client.resume?.();
      } catch {
        if (upstream) upstream.destroy();
        if (!client.destroyed) {
          if (tunnelAccepted) client.destroy();
          else endWithStatus(client, 502, "Bad Gateway");
        }
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
