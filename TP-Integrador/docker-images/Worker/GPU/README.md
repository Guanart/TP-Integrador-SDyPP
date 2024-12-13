# Como ejecutar el worker-gpu para conectarse al coordinador:
## Windows:
```
set COORDINATOR_HOST=35.243.231.77 && set COORDINATOR_PORT=5000 && set KEEPALIVE_HOST=35.243.231.77 && set KEEPALIVE_PORT=5001 && set RABBITMQ_HOST=35.243.231.77 && set RABBITMQ_PORT=5672 && python .\worker_gpu.py
```