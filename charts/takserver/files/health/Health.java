// Copyright 2026 uds-k3d-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

// SPIKE: answers each uptime path from the result files health.sh writes.
// 200 when the last check passed and is newer than STALE_SECONDS, else 503.
// Uses the JDK's built-in HTTP server, so no extra image or dependency.

import com.sun.net.httpserver.HttpServer;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Set;

public class Health {
  public static void main(String[] args) throws Exception {
    int port = Integer.parseInt(System.getenv().getOrDefault("PORT", "8081"));
    long stale = Long.parseLong(System.getenv().getOrDefault("STALE_SECONDS", "90"));
    Path dir = Path.of(System.getenv().getOrDefault("STATE_DIR", "/tmp/health"));
    Set<String> checks = Set.of("stream", "api", "enroll");
    HttpServer server = HttpServer.create(new InetSocketAddress(port), 32);
    server.createContext("/", exchange -> {
      String name = exchange.getRequestURI().getPath().substring(1);
      int code = 404;
      String body = "";
      if (name.equals("healthz")) {
        code = 200;
        body = "ok\n";
      } else if (checks.contains(name)) {
        code = 503;
        body = name + " no result yet\n";
        try {
          String[] f = Files.readString(dir.resolve(name)).trim().split(" ", 3);
          long age = System.currentTimeMillis() / 1000 - Long.parseLong(f[0]);
          body = name + " ok=" + f[1] + " age=" + age + "s " + (f.length > 2 ? f[2] : "") + "\n";
          if (f[1].equals("1") && age <= stale) {
            code = 200;
          }
        } catch (Exception e) {
          // No result file yet: 503.
        }
      }
      byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
      exchange.getResponseHeaders().set("Content-Type", "text/plain");
      exchange.sendResponseHeaders(code, bytes.length == 0 ? -1 : bytes.length);
      if (bytes.length > 0) {
        exchange.getResponseBody().write(bytes);
      }
      exchange.close();
    });
    server.start();
  }
}
