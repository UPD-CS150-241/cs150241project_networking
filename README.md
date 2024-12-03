# `cs150241project_networking`

To install into your Poetry project:

```bash
poetry add git+https://github.com/UPD-CS150-241/cs150241project_networking
```

Sample usage with `pygame-ce`; run two instances of code below with fresh instance of [https://github.com/UPD-CS150-241/project-server](https://github.com/UPD-CS150-241/project-server):

```python
import pygame
import random
from cs150241project_networking import CS150241ProjectNetworking

pygame.init()

width = 600
height = 400
screen = pygame.display.set_mode((width, height))
clock = pygame.time.Clock()
fps = 30
frame_count = 0
networking = CS150241ProjectNetworking.connect('localhost', 15000)

latest_message = None

font = pygame.font.SysFont("", 24)
id_text_obj = font.render(f"You are Player {networking.player_id}", False, 'white')

while True:
    if random.randint(1, 100) <= 2:
        print(f'Sending frame count: {frame_count}')
        networking.send(
            f'Frame count of Player {networking.player_id} is {frame_count}')

    for _ in pygame.event.get():
        pass

    for m in networking.recv():
        latest_message = m

    screen.fill('black')

    screen.blit(
        id_text_obj,
        (width // 2 - id_text_obj.width // 2, height // 2 - id_text_obj.height // 2 - 50)
    )

    if latest_message is not None:
        text_obj = font.render(
            f'Message from Player {latest_message.source}: {latest_message.payload}', False, 'white')
        screen.blit(
            text_obj,
            (width // 2 - text_obj.width // 2, height // 2 - text_obj.height // 2 + 50)
        )

    pygame.display.flip()

    clock.tick(fps)
    frame_count += 1
```

Each client above intermittently sends their current frame count which is broadcasted to all clients in the room.

Note that the sending client _also_ receives the message they just sent.
