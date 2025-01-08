import json
import pika

try:
    rabbitmq_queue = 'cola_prueba'
    credentials = pika.PlainCredentials("user", "password")
    parameters = pika.ConnectionParameters(host="34.73.222.114", port=5672, credentials=credentials, heartbeat=0)
    connection = pika.BlockingConnection(parameters)
    channel = connection.channel()
    channel.confirm_delivery()
    channel.queue_declare(queue=rabbitmq_queue, durable=True)
    print("Conectado correctamente")
except Exception as e:
    print(f"Ocurrió un ERROR: {e}")


data = {
    "hola": "chau",
    "chau": "hola"
}


if channel.basic_publish(exchange='', routing_key=rabbitmq_queue, body=json.dumps(data)):
    print("Mensaje publicado con éxito.")
else:
    print("El mensaje no pudo ser publicado.")


# Comprobar el mensaje
# method_frame, header_frame, body = channel.basic_get(queue=rabbitmq_queue, auto_ack=True)
# if method_frame:
#     print("Mensaje obtenido de la cola:", json.loads(body))
# else:
#     print("La cola está vacía o no se pudo obtener el mensaje.")
