#!/usr/bin/env python3
"""Create circular icon.png and icon.ico from original icon.png"""

from PIL import Image, ImageDraw

def create_circular_icon(input_path='icon.png', output_png='icon.png', output_ico='icon.ico'):
    """Convert image to circular and save as png and ico"""
    # Open original image
    img = Image.open(input_path).convert('RGBA')
    size = img.size
    
    # Create circular mask
    mask = Image.new('L', size, 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((0, 0, size[0], size[1]), fill=255)
    
    # Apply circular mask
    output = Image.new('RGBA', size, (0, 0, 0, 0))
    output.paste(img, mask=mask)
    
    # Save circular PNG
    output.save(output_png)
    print(f'Circular {output_png} created successfully!')
    
    # Save as ICO with multiple sizes
    output.save(output_ico, sizes=[(16,16), (32,32), (48,48), (64,64), (128,128), (256,256)])
    print(f'{output_ico} created successfully!')

if __name__ == '__main__':
    create_circular_icon()
