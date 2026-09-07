import socket
import threading
import sys

def forward(src, dst):
    try:
        while True:
            data = src.recv(4096)
            if not data:
                break
            dst.sendall(data)
    except Exception:
        pass
    finally:
        try:
            src.close()
        except Exception:
            pass
        try:
            dst.close()
        except Exception:
            pass

def handle_client(client_socket, target_host, target_port):
    try:
        target_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        target_socket.connect((target_host, target_port))
    except Exception as e:
        print(f"Failed to connect to target {target_host}:{target_port}: {e}")
        client_socket.close()
        return

    threading.Thread(target=forward, args=(client_socket, target_socket), daemon=True).start()
    threading.Thread(target=forward, args=(target_socket, client_socket), daemon=True).start()

def main():
    listen_host = "127.0.0.1"
    listen_port = 8765
    target_host = "host.docker.internal"
    target_port = 8765

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.bind((listen_host, listen_port))
    except Exception as e:
        print(f"Failed to bind to {listen_host}:{listen_port}: {e}")
        sys.exit(1)

    server.listen(100)
    print(f"Listening on {listen_host}:{listen_port}, forwarding to {target_host}:{target_port}...")

    try:
        while True:
            client, addr = server.accept()
            handle_client(client, target_host, target_port)
    except KeyboardInterrupt:
        print("Shutting down...")
    finally:
        server.close()

if __name__ == "__main__":
    main()
