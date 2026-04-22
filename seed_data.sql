WITH service_nodes AS (
    INSERT INTO nodes (type, label, metadata, source_url)
    VALUES
        ('service', 'payments', '{"domain":"payments"}'::jsonb, 'seed://service/payments'),
        ('service', 'gateway', '{"domain":"platform"}'::jsonb, 'seed://service/gateway'),
        ('service', 'auth', '{"domain":"security"}'::jsonb, 'seed://service/auth'),
        ('service', 'notifications', '{"domain":"messaging"}'::jsonb, 'seed://service/notifications')
    RETURNING id, label
),
author_nodes AS (
    INSERT INTO nodes (type, label, metadata, source_url)
    VALUES
        ('author', 'dinol', '{"team":"backend"}'::jsonb, 'seed://author/dinol'),
        ('author', 'rahul', '{"team":"backend"}'::jsonb, 'seed://author/rahul'),
        ('author', 'team-lead', '{"team":"platform"}'::jsonb, 'seed://author/team-lead')
    RETURNING id, label
),
decision_nodes AS (
    INSERT INTO nodes (type, label, metadata, source_url)
    VALUES
        (
            'decision',
            'Rate limiting at API Gateway',
            '{"reason":"Centralized throttling protects downstream services and keeps policy enforcement consistent.","services":["gateway","payments"]}'::jsonb,
            'seed://decision/rate-limiting-at-api-gateway'
        ),
        (
            'decision',
            'JWT auth centralized',
            '{"reason":"Single auth boundary reduces duplicate token validation logic and closes policy drift.","services":["auth","gateway"]}'::jsonb,
            'seed://decision/jwt-auth-centralized'
        ),
        (
            'decision',
            'Retries only idempotent endpoints',
            '{"reason":"Prevent duplicate side effects while still improving reliability for safe operations.","services":["payments","notifications"]}'::jsonb,
            'seed://decision/retries-only-idempotent-endpoints'
        ),
        (
            'decision',
            'Payment webhook async queue',
            '{"reason":"Queueing webhook work smooths burst traffic and isolates provider latency spikes.","services":["payments","notifications"]}'::jsonb,
            'seed://decision/payment-webhook-async-queue'
        )
    RETURNING id, label
),
decision_author_edges AS (
    INSERT INTO edges (from_node_id, to_node_id, relation)
    SELECT d.id, a.id, 'owned_by_author'
    FROM decision_nodes d
    JOIN author_nodes a
      ON (d.label = 'Rate limiting at API Gateway' AND a.label = 'team-lead')
      OR (d.label = 'JWT auth centralized' AND a.label = 'dinol')
      OR (d.label = 'Retries only idempotent endpoints' AND a.label = 'rahul')
      OR (d.label = 'Payment webhook async queue' AND a.label = 'dinol')
    ON CONFLICT (from_node_id, to_node_id, relation) DO NOTHING
    RETURNING from_node_id
)
INSERT INTO edges (from_node_id, to_node_id, relation)
SELECT d.id, s.id, 'affects_service'
FROM decision_nodes d
JOIN service_nodes s
  ON (d.label = 'Rate limiting at API Gateway' AND s.label IN ('gateway', 'payments'))
  OR (d.label = 'JWT auth centralized' AND s.label IN ('auth', 'gateway'))
  OR (d.label = 'Retries only idempotent endpoints' AND s.label IN ('payments', 'notifications'))
  OR (d.label = 'Payment webhook async queue' AND s.label IN ('payments', 'notifications'))
ON CONFLICT (from_node_id, to_node_id, relation) DO NOTHING;
