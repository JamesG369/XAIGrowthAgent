<?php
header('Content-Type: application/json');
header('Access-Control-Allow-Origin: *');
header('Access-Control-Allow-Methods: GET, OPTIONS');
header('Access-Control-Allow-Headers: Content-Type');

if ($_SERVER['REQUEST_METHOD'] === 'OPTIONS') {
    http_response_code(200);
    exit;
}

$userId = '2036579154360188928';
$bearer = 'AAAAAAAAAAAAAAAAAAAAABAb8gEAAAAAHSBtX77NM090FVCYCCuSBl%2BCbco%3Db5ONEg5pN9FpgszYDdVwtjTOukUNsGjK9DKZxSYVqvrkgYZ7Wc';
$url = "https://api.twitter.com/2/users/$userId?user.fields=public_metrics";

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
    echo json_encode(['error'=>'API error','raw'=>$response]);
}
?>
