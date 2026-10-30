<?php
header('Content-Type: application/json');
header('Access-Control-Allow-Origin: *');
header('Access-Control-Allow-Methods: GET, OPTIONS');
header('Access-Control-Allow-Headers: Content-Type');

if ($_SERVER['REQUEST_METHOD'] === 'OPTIONS') {
    http_response_code(200);
    exit;
}

// Configure on the host (never commit the token):
//   X_BEARER_TOKEN  X/Twitter API v2 bearer token (required)
//   X_USER_ID       numeric X user ID (optional, defaults below)
// e.g. Apache: SetEnv X_BEARER_TOKEN ... ; nginx/php-fpm: env[X_BEARER_TOKEN] = ...
$bearer = getenv('X_BEARER_TOKEN');
if ($bearer === false || $bearer === '') {
    http_response_code(500);
    echo json_encode(['error'=>'X_BEARER_TOKEN not set']);
    exit;
}
$userId = getenv('X_USER_ID') ?: '2036579154360188928';
$url = "https://api.twitter.com/2/users/" . rawurlencode($userId) . "?user.fields=public_metrics";

$ch = curl_init($url);
curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
curl_setopt($ch, CURLOPT_HTTPHEADER, ["Authorization: Bearer $bearer"]);
$response = curl_exec($ch);
curl_close($ch);

$data = json_decode($response, true);

if (isset($data['data'])) {
    $m = $data['data']['public_metrics'];
    echo json_encode([
        'account'=>[
            'username'=>$data['data']['username'],
            'followers'=>$m['followers_count'],
            'following'=>$m['following_count'],
            'tweets'=>$m['tweet_count'],
            'likes'=>$m['like_count']
        ],
        'last_updated'=>date('c')
    ]);
} else {
    http_response_code(502);
    echo json_encode(['error'=>'API error']);
}
?>
