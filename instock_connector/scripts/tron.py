# Generates the grid, which is defined as:

# “The Grid. A digital frontier. I tried to picture clusters of information as
# they moved through the computer. What did they look like? Ships, motorcycles?
# Were the circuits like freeways? I kept dreaming of a world I thought I'd
# never see. And then, one day I got in...”

import json

size = 1.2
grid_points = []

# Traverse the first row from left to right
for i in range(9):
    grid_points.append([i * size, 0])  # Top left
    grid_points.append([(i + 1) * size, 0])  # Top right
    grid_points.append([(i + 1) * size, size])  # Bottom right
    grid_points.append([i * size, size])  # Bottom left
    grid_points.append([i * size, 0])  # Back to top left

# Bottom left of last cell in the first row
grid_points.append([8 * size, size])
# Bottom left of last cell in the second row
grid_points.append([8 * size, 2 * size])

# Traverse the second row from right to left
for i in range(8, -1, -1):
    grid_points.append([(i + 1) * size, 2 * size])  # Bottom right
    grid_points.append([i * size, 2 * size])  # Bottom left
    grid_points.append([i * size, size])  # Top left
    if i != 0:
        grid_points.append([(i + 1) * size, size])  # Top right
        grid_points.append([(i + 1) * size, 2 * size])  # Back to bottom right

json_grid = json.dumps(grid_points)
print(json_grid)
