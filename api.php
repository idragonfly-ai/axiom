<?php
// api_axiom.php - Unified Axiom Endpoint with External JSON Config
header('Content-Type: application/json; charset=utf-8');

$config_file = __DIR__ . '/axiom.json';
if (!file_exists($config_file)) {
    echo json_encode(['error' => 'Missing axiom.json configuration file.'], JSON_PRETTY_PRINT);
    exit;
}

$config = json_decode(file_get_contents($config_file), true);
$db_cfg = $config['database'];

$mysqli = new mysqli(
    $db_cfg['host'],
    $db_cfg['user'],
    $db_cfg['password'],
    $db_cfg['database']
);

if ($mysqli->connect_errno) {
    echo json_encode(['error' => 'Database connection failed: ' . $mysqli->connect_error], JSON_PRETTY_PRINT);
    exit;
}

$mysqli->set_charset($db_cfg['charset'] ?? 'utf8mb4');

$input_data = [];
$raw_input = file_get_contents('php://input');
if (!empty($raw_input)) {
    $decoded = json_decode($raw_input, true);
    if (is_array($decoded)) {
        $input_data = $decoded;
    }
}

$q_arg = '';
if (isset($input_data['q'])) {
    $q_arg = trim($input_data['q']);
} elseif (isset($_POST['q'])) {
    $q_arg = trim($_POST['q']);
} elseif (isset($_GET['q'])) {
    $q_arg = trim($_GET['q']);
}

$type_arg = '';
if (isset($input_data['type'])) {
    $type_arg = trim($input_data['type']);
} elseif (isset($_POST['type'])) {
    $type_arg = trim($_POST['type']);
} elseif (isset($_GET['type'])) {
    $type_arg = trim($_GET['type']);
}

$uri_arg = '';
if (isset($input_data['uri'])) {
    $uri_arg = trim($input_data['uri']);
} elseif (isset($_POST['uri'])) {
    $uri_arg = trim($_POST['uri']);
} elseif (isset($_GET['uri'])) {
    $uri_arg = trim($_GET['uri']);
}

if ($q_arg === '') {
    echo json_encode(['error' => 'Missing query parameter q.'], JSON_PRETTY_PRINT);
    $mysqli->close();
    exit;
}

$safe_raw_q = $mysqli->real_escape_string($q_arg);
$default_id = $mysqli->real_escape_string(strtolower(str_replace(' ', '_', $q_arg)));

$target_cid = null;
$alias_sql  = "SELECT concept_id FROM axiom_aliases WHERE alias_text = '$safe_raw_q' LIMIT 1";
$alias_res  = $mysqli->query($alias_sql);
if ($alias_res && $alias_res->num_rows > 0) {
    $arow = $alias_res->fetch_assoc();
    $target_cid = $arow['concept_id'];
}

$type_clause = '';
if ($type_arg !== '') {
    $safe_type   = $mysqli->real_escape_string($type_arg);
    $type_clause = "AND concept_type = '$safe_type'";
}

if ($target_cid !== null) {
    $safe_target_cid = $mysqli->real_escape_string($target_cid);
    $sql_concept = "
        SELECT concept_id, canonical_name, concept_type, summary_markdown, structured_payload, primary_source_id, updated_at
        FROM axiom_concepts
        WHERE concept_id = '$safe_target_cid' $type_clause
        LIMIT 1
    ";
} else {
    $sql_concept = "
        SELECT concept_id, canonical_name, concept_type, summary_markdown, structured_payload, primary_source_id, updated_at
        FROM axiom_concepts
        WHERE (concept_id = '$default_id' OR canonical_name = '$safe_raw_q') $type_clause
        LIMIT 1
    ";
}

$res = $mysqli->query($sql_concept);
if ($res && $res->num_rows > 0) {
    $row = $res->fetch_assoc();
    $cid = $row['concept_id'];
    $safe_cid = $mysqli->real_escape_string($cid);

    $edges_sql = "
        SELECT source_concept_id, target_concept_id, relation_type, context_snippet, confidence_weight, source_reference_id
        FROM axiom_edges
        WHERE source_concept_id = '$safe_cid' OR target_concept_id = '$safe_cid'
    ";
    $edges_res = $mysqli->query($edges_sql);
    $edges = [];
    if ($edges_res) {
        while ($erow = $edges_res->fetch_assoc()) {
            $dir = ($erow['source_concept_id'] === $cid) ? 'outgoing' : 'incoming';
            $connected_node = ($dir === 'outgoing') ? $erow['target_concept_id'] : $erow['source_concept_id'];
            $edges[] = [
                'direction' => $dir,
                'related_node_id' => $connected_node,
                'relation_type' => $erow['relation_type'],
                'context_snippet' => $erow['context_snippet'],
                'confidence_weight' => (float)$erow['confidence_weight'],
                'source_reference_id' => $erow['source_reference_id']
            ];
        }
    }

    $source_meta = null;
    if (!empty($row['primary_source_id'])) {
        $psafe = $mysqli->real_escape_string($row['primary_source_id']);
        $sres  = $mysqli->query("SELECT source_type, title, uri, publication_date FROM axiom_sources WHERE source_id = '$psafe' LIMIT 1");
        if ($sres && $sres->num_rows > 0) {
            $source_meta = $sres->fetch_assoc();
        }
    }

    echo json_encode([
        'status' => 'hit',
        'resolved_via' => ($target_cid !== null) ? 'alias' : 'direct',
        'concept_id' => $row['concept_id'],
        'canonical_name' => $row['canonical_name'],
        'concept_type' => $row['concept_type'],
        'summary_markdown' => $row['summary_markdown'],
        'payload' => json_decode($row['structured_payload'], true),
        'primary_source' => $source_meta,
        'edges' => $edges,
        'cached_at' => $row['updated_at']
    ], JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES);
} else {
    $safe_qtype = $type_arg !== '' ? $mysqli->real_escape_string($type_arg) : '';
    $safe_uri = $uri_arg !== '' ? $mysqli->real_escape_string($uri_arg) : '';

    $queue_check_sql = "SELECT status FROM axiom_queue WHERE query_text = '$safe_raw_q' ORDER BY queue_id DESC LIMIT 1";
    $queue_res = $mysqli->query($queue_check_sql);

    $queue_status = null;
    if ($queue_res && $queue_res->num_rows > 0) {
        $qrow = $queue_res->fetch_assoc();
        $queue_status = $qrow['status'];
    }

    if ($queue_status === null) {
        $uri_val = ($safe_uri !== '') ? "'$safe_uri'" : "NULL";
        $mysqli->query("
            INSERT INTO axiom_queue (query_text, requested_type, uri, status, created_at, updated_at)
            VALUES ('$safe_raw_q', " . ($safe_qtype !== '' ? "'$safe_qtype'" : "NULL") . ", $uri_val, 'pending', NOW(), NOW())
        ");
        $queue_status = 'pending';
    } elseif ($queue_status === 'failed') {
        $uri_val = ($safe_uri !== '') ? "'$safe_uri'" : "NULL";
        $mysqli->query("
            INSERT INTO axiom_queue (query_text, requested_type, uri, status, created_at, updated_at)
            VALUES ('$safe_raw_q', " . ($safe_qtype !== '' ? "'$safe_qtype'" : "NULL") . ", $uri_val, 'pending', NOW(), NOW())
        ");
        $queue_status = 'pending';
    }

    $message = 'Concept miss. Enqueued for local RAG synthesis worker.';
    if ($queue_status === 'pending') {
        $message = 'Concept miss. Request is currently pending in the ingestion queue.';
    } elseif ($queue_status === 'processing') {
        $message = 'Concept miss. Request is currently being processed by the RAG synthesis worker.';
    } elseif ($queue_status === 'completed') {
        $message = 'Concept miss. Processing completed; concept will be available shortly.';
    }

    echo json_encode([
        'status' => 'miss',
        'query' => $q_arg,
        'default_concept_id' => $default_id,
        'queue_status' => $queue_status,
        'message' => $message
    ], JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES);
}

$mysqli->close();
?>
