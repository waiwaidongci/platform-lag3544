import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from sqlalchemy import text
from scripts.seed_demo import seed
from src.config.database import Base, engine
from src.config.settings import SEED_DEMO
from src.domain.spec import SPEC
from src.middlewares import errors, headers, rate
from src.routes import distribution, identity, registry, runs, swap
from src.services.swap import recover_interrupted
from src.utils.wakeup import broker

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app):
    Base.metadata.create_all(engine)
    if SEED_DEMO:
        try:
            log.info('Seeded %s', seed())
        except Exception:
            log.exception('Demo seed failed')
    try:
        recovered = recover_interrupted()
        if recovered:
            log.info('Recovered %s interrupted swap publications', recovered)
    except Exception:
        log.exception('Swap publication recovery failed')
    yield
    engine.dispose()


app = FastAPI(title=SPEC['title'], lifespan=lifespan)
errors.install(app)
headers.install(app)
rate.install(app)
for module in (identity, registry, runs, swap):
    app.include_router(module.router)
if SPEC.get('scheduled'):
    app.include_router(distribution.router)


@app.get('/healthz', include_in_schema=False)
def health():
    with engine.connect() as connection:
        connection.execute(text('SELECT 1'))
    broker.ping()
    return {'status': 'ok'}
