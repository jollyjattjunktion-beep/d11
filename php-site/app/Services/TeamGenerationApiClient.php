<?php
declare(strict_types=1);

namespace D11\\Services;

use RuntimeException;

/**
 * Small, fixed-host TeamGeneration API client.
 * Credentials are read only from the server environment; never from a form or URL.
 */
final class TeamGenerationApiClient
{
    private const BASE_URL = 'https://v2.tgsoftware-api.online';

    private function token(): string
    {
        $token = trim((string)(getenv('TG_API_TOKEN') ?: ''));
        if ($token === '') {
            throw new RuntimeException('TeamGeneration is not configured. Set TG_API_TOKEN in the PHP hosting environment.');
        }
        return $token;
    }

    private function get(string $path): array
    {
        if (!preg_match('#^/(matches(?:/([A-Za-z0-9_-]+))?(?:\\?sport=cricket)?)$#', $path, $m)) {
            throw new RuntimeException('Invalid TeamGeneration API path.');
        }
        if (!function_exists('curl_init')) {
            throw new RuntimeException('PHP cURL extension is required for TeamGeneration imports.');
        }

        $curl = curl_init(self::BASE_URL . $path);
        curl_setopt_array($curl, [
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_FOLLOWLOCATION => false,
            CURLOPT_CONNECTTIMEOUT => 8,
            CURLOPT_TIMEOUT => 25,
            CURLOPT_HTTPHEADER => [
                'Authorization: Bearer ' . $this->token(),
                'Accept: application/json',
                'Cache-Control: no-cache',
                'Pragma: no-cache',
            ],
            CURLOPT_SSL_VERIFYPEER => true,
            CURLOPT_SSL_VERIFYHOST => 2,
        ]);
        $body = curl_exec($curl);
        $error = curl_error($curl);
        $status = (int)curl_getinfo($curl, CURLINFO_HTTP_CODE);
        curl_close($curl);

        if ($body === false) {
            throw new RuntimeException('Could not reach TeamGeneration API: ' . ($error ?: 'network error'));
        }
        if ($status === 401) {
            throw new RuntimeException('TeamGeneration rejected TG_API_TOKEN (401). Refresh the authenticated API token and update the server environment.');
        }
        if ($status === 403) {
            throw new RuntimeException('TeamGeneration denied access (403). The signed-in account/token may not have permission for this match.');
        }
        if ($status < 200 || $status >= 300) {
            throw new RuntimeException('TeamGeneration API returned HTTP ' . $status . ': ' . substr((string)$body, 0, 500));
        }
        try {
            $data = json_decode((string)$body, true, 64, JSON_THROW_ON_ERROR);
        } catch (\\JsonException $e) {
            throw new RuntimeException('TeamGeneration returned invalid JSON.', 0, $e);
        }
        if (!is_array($data)) {
            throw new RuntimeException('TeamGeneration returned an unexpected JSON shape.');
        }
        return $data;
    }

    public function listCricketFixtures(): array
    {
        $data = $this->get('/matches?sport=cricket');
        if (!array_is_list($data)) {
            throw new RuntimeException('TeamGeneration fixture feed did not return a JSON list.');
        }
        return $data;
    }

    public function getMatch(string $matchId): array
    {
        $matchId = trim($matchId);
        if ($matchId === '' || strlen($matchId) > 50 || !preg_match('/^[A-Za-z0-9_-]+$/', $matchId)) {
            throw new RuntimeException('Invalid TeamGeneration match ID.');
        }
        return $this->get('/matches/' . rawurlencode($matchId));
    }
}
