# Tiltfile — live-reload development on kind cluster.
# Usage: tilt up (requires kind cluster running via `make dev-k8s`)
#
# This gives you hot-reload for all services on the local k8s cluster,
# same shape as production but with fast iteration.

# ─── Configuration ───────────────────────────────────────────────────────────

allow_k8s_contexts('kind-astraeus-local')

# ─── API Service ─────────────────────────────────────────────────────────────

docker_build(
    'ghcr.io/astraeus/api',
    context='.',
    dockerfile='apps/api/Dockerfile',
    live_update=[
        sync('apps/api/astraeus_api', '/app/astraeus_api'),
        sync('libs/', '/app/libs'),
        run('pip install -e /app', trigger=['apps/api/pyproject.toml']),
    ],
)

k8s_yaml(helm(
    'apps/api/deploy/chart',
    name='api',
    namespace='research',
    values=['gitops/overlays/dev/api-values.yaml'],
    set=[
        'image.repository=ghcr.io/astraeus/api',
        'image.tag=latest',
        'image.pullPolicy=Never',
        'rollout.enabled=false',
        'nodeSelector=null',
    ],
))

k8s_resource('api-astraeus-api', port_forwards='8000:8000', labels=['research'])

# ─── Workers Service ─────────────────────────────────────────────────────────

docker_build(
    'ghcr.io/astraeus/workers',
    context='.',
    dockerfile='apps/workers/Dockerfile',
    live_update=[
        sync('apps/workers/astraeus_workers', '/app/astraeus_workers'),
        sync('libs/', '/app/libs'),
        run('pip install -e /app', trigger=['apps/workers/pyproject.toml']),
    ],
)

k8s_yaml(helm(
    'apps/workers/deploy/chart',
    name='workers',
    namespace='research',
    set=[
        'image.repository=ghcr.io/astraeus/workers',
        'image.tag=latest',
        'image.pullPolicy=Never',
        'autoscaling.enabled=false',
        'replicaCount=1',
        'nodeSelector=null',
        'networkPolicy.enabled=false',
    ],
))

k8s_resource('workers-astraeus-workers', labels=['research'])

# ─── OMS Service ─────────────────────────────────────────────────────────────

docker_build(
    'ghcr.io/astraeus/oms',
    context='.',
    dockerfile='apps/oms/Dockerfile' if os.path.exists('apps/oms/Dockerfile') else 'apps/api/Dockerfile',
    live_update=[
        sync('apps/oms/astraeus_oms', '/app/astraeus_oms'),
        sync('libs/', '/app/libs'),
    ],
)

k8s_yaml(helm(
    'apps/oms/deploy/chart',
    name='oms',
    namespace='trading',
    set=[
        'image.repository=ghcr.io/astraeus/oms',
        'image.tag=latest',
        'image.pullPolicy=Never',
        'rollout.enabled=false',
        'nodeSelector=null',
        'tolerations=null',
        'networkPolicy.enabled=false',
    ],
))

k8s_resource('oms-astraeus-oms', port_forwards='8001:8000', labels=['trading'])

# ─── Web Service ─────────────────────────────────────────────────────────────

docker_build(
    'ghcr.io/astraeus/web',
    context='apps/web',
    dockerfile='apps/web/Dockerfile' if os.path.exists('apps/web/Dockerfile') else None,
    live_update=[
        sync('apps/web/src', '/app/src'),
        sync('apps/web/public', '/app/public'),
        run('npm install', trigger=['apps/web/package.json']),
    ],
    ignore=['node_modules', '.next'],
)

k8s_yaml(helm(
    'apps/web/deploy/chart',
    name='web',
    namespace='web',
    set=[
        'image.repository=ghcr.io/astraeus/web',
        'image.tag=latest',
        'image.pullPolicy=Never',
        'rollout.enabled=false',
        'autoscaling.enabled=false',
        'replicaCount=1',
        'nodeSelector=null',
        'networkPolicy.enabled=false',
    ],
))

k8s_resource('web-astraeus-web', port_forwards='3000:3000', labels=['web'])

# ─── Resource Groups ─────────────────────────────────────────────────────────

# Group resources for the Tilt UI
config.define_string_list('services', args=True)
cfg = config.parse()
enabled_services = cfg.get('services', ['api', 'workers', 'oms', 'web'])
