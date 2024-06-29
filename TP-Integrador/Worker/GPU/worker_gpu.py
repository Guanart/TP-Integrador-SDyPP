import pika
import requests
import minero_gpu
import json
import time

#Enviar el resultado al coordinador para verificar que el resultado es correcto
def post_result(data):
    url = "http://localhost:5000/solved_task"
    try:
        response = requests.post(url, json=data)
        print("Post response:", response.text)
    except requests.exceptions.RequestException as e:
        print("Failed to send POST request:", e)

# #Minero: Encargado de realizar el desafio
def minero(ch, method, properties, body):
    data = json.loads(body)
    print(f"Message {data} received")
    start_time = time.time()
    print("Starting mining process...")

    # En nuestra versión llega esto en data:
    '''
    data = {
        "id": last_id,
        "transactions": transactions, 
        "prefix": prefix,
        "num_max": 99999999,
        "last_hash": last_element["hash"] if last_element else ""
    }
    '''

    resultado = minero_gpu.ejecutar_minero(1, data["num_max"], data["prefix"], str(len(data['transactions'])) + data["last_hash"])
    processing_time = time.time() - start_time
    resultado = json.loads(resultado)
    print(f"Resultado: {resultado}")

    data["hash"] = resultado['hash_md5_result']
    data["number"] = resultado["numero"]

    post_result(data)
    print(f"Resultado encontrado y posteado para el block con ID {data['id']} en {processing_time:.2f} segundos")
    ch.basic_ack(delivery_tag=method.delivery_tag)

#Conexion con rabbit al topico y comienza a ser consumidor
def main():
    # Configuración de RabbitMQ
    rabbitmq_host = 'localhost'
    rabbitmq_port = 5672
    connected_rabbit = False
    while not connected_rabbit:
        try:
            connection = pika.BlockingConnection(pika.ConnectionParameters(host=rabbitmq_host, port=rabbitmq_port, credentials=pika.PlainCredentials('guest', 'guest'), heartbeat=0))
            channel = connection.channel()
            channel.exchange_declare(exchange='blockchain_challenge', exchange_type='topic', durable=True)
            result = channel.queue_declare('', exclusive=True)
            queue_name = result.method.queue
            channel.queue_bind(exchange='blockchain_challenge', queue=queue_name, routing_key='tasks')
            connected_rabbit = True
            print("Ya se encuentra conectado a RabbitMQ!")
        except Exception as e:
            print(f"Error connectando a RabbitMQ: {e}")
            print("Reintentando en 3 segundos...")
            time.sleep(3)

    channel.basic_consume(queue=queue_name, on_message_callback=minero, auto_ack=False)
    print('Waiting for messages. To exit press CTRL+C')
    try:
        channel.start_consuming()
    except KeyboardInterrupt:
        print("Consumption stopped by user.")
        connection.close()
        print("Connection closed.")

if __name__ == '__main__':
    main()