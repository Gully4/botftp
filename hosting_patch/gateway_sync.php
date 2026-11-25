<?php
declare(strict_types=1);
// NEON OS V32: authenticated receiver for the changing Cloudflare Quick Tunnel URL.
define('NEON_BOOTSTRAP', true);
header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');

function neon_sync_reply(int $status, array $payload): never {
    http_response_code($status);
    echo json_encode($payload, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
    exit;
}

if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') {
    header('Allow: POST');
    neon_sync_reply(405, ['ok' => false, 'error' => 'Method POST required']);
}

try {
    require_once __DIR__ . '/config.php';
    require_once __DIR__ . '/neon_runtime.php';
} catch (Throwable $e) {
    neon_sync_reply(500, ['ok' => false, 'error' => 'Hosting bootstrap failed']);
}

$expected = defined('NEON_GATEWAY_SYNC_TOKEN') ? (string) NEON_GATEWAY_SYNC_TOKEN : '';
$auth = (string) ($_SERVER['HTTP_AUTHORIZATION'] ?? '');
if ($auth === '' && function_exists('getallheaders')) {
    $headers = getallheaders();
    $auth = (string) ($headers['Authorization'] ?? $headers['authorization'] ?? '');
}
if ($expected === '' || strlen($expected) < 32 || !preg_match('/^Bearer\s+(.+)$/i', $auth, $m)
    || !hash_equals($expected, trim($m[1]))) {
    neon_sync_reply(403, ['ok' => false, 'error' => 'Forbidden']);
}

$length = (int) ($_SERVER['CONTENT_LENGTH'] ?? 0);
if ($length > 4096) neon_sync_reply(413, ['ok' => false, 'error' => 'Payload too large']);
$raw = file_get_contents('php://input', false, null, 0, 4096);
$data = json_decode((string) $raw, true);
$url = is_array($data) ? trim((string) ($data['url'] ?? '')) : '';
$parts = $url !== '' ? parse_url($url) : false;
$host = strtolower((string) ($parts['host'] ?? ''));
if (!$parts || strtolower((string) ($parts['scheme'] ?? '')) !== 'https'
    || !preg_match('/^[a-z0-9-]+\.trycloudflare\.com$/', $host)
    || isset($parts['user']) || isset($parts['pass']) || isset($parts['query'])
    || isset($parts['fragment']) || (isset($parts['path']) && !in_array($parts['path'], ['', '/'], true))) {
    neon_sync_reply(400, ['ok' => false, 'error' => 'Invalid Cloudflare Quick Tunnel URL']);
}

try {
    $runtime = neon_runtime_dir();
    if (!is_dir($runtime) && !mkdir($runtime, 0700, true) && !is_dir($runtime)) {
        throw new RuntimeException('Runtime directory unavailable');
    }
    $target = rtrim($runtime, DIRECTORY_SEPARATOR) . DIRECTORY_SEPARATOR . 'gateway_url.txt';
    $tmp = $target . '.tmp.' . bin2hex(random_bytes(5));
    $value = rtrim($url, '/') . "\n";
    if (file_put_contents($tmp, $value, LOCK_EX) === false || !rename($tmp, $target)) {
        @unlink($tmp);
        throw new RuntimeException('Atomic write failed');
    }
    @chmod($target, 0600);
    @file_put_contents(rtrim($runtime, DIRECTORY_SEPARATOR) . DIRECTORY_SEPARATOR . 'gateway_url_updated.txt', gmdate('c') . "\n", LOCK_EX);
    neon_sync_reply(200, ['ok' => true, 'message' => 'Gateway URL updated', 'updated_at' => gmdate('c')]);
} catch (Throwable $e) {
    neon_sync_reply(500, ['ok' => false, 'error' => 'Could not persist gateway URL']);
}
