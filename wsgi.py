"""
WSGI entrypoint for production (gunicorn + gevent).

Render y otros PaaS usan este archivo como Start Command:

    gunicorn wsgi:app -k geventwebsocket.worker -w 1 --worker-connections 1000

- 1 worker: necesario para que SocketIO mantenga estado compartido de
  salas de chat entre todos los clientes conectados.
- geventwebsocket.worker: habilita WebSocket dentro de gunicorn sin
  necesidad de un message queue externo (Redis).
- --worker-connections 1000: concurrentes por worker (gevent greenlets).
"""
from app import app

# gunicorn usa `wsgi:app` como WSGI callable.
