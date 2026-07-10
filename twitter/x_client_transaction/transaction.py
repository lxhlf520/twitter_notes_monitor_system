import re
import math
import time
import random
import base64
import hashlib
from typing import List
from functools import reduce

from bs4 import BeautifulSoup
from .cubic_curve import Cubic
from .interpolate import interpolate
from .rotation import convert_rotation_to_matrix
from .utils import float_to_hex, is_odd, base64_encode


class ClientTransaction:

    ADDITIONAL_RANDOM_NUMBER = 3

    DEFAULT_KEYWORD = "obfiowerehiring"

    DEFAULT_ANIMATION_KEY = "e48fc9100100"
    
    def __init__(self, home_page_response: BeautifulSoup, key_byte_indices: List):
        self.key_bytes = self.get_key_bytes(home_page_response)
        self.DEFAULT_ROW_INDEX, self.DEFAULT_KEY_BYTES_INDICES = key_byte_indices[0], key_byte_indices[1:]
        self.get_2d_array(home_page_response)
        self.get_animation_key()
        
    @classmethod
    def from_cache(cls, key_bytes, key_byte_indices, arr_2d):
        """
        从缓存数据构造 ClientTransaction 实例（无需 Playwright）

        Args:
            key_bytes: meta 标签 content base64 解码后的字节列表
            key_byte_indices: ondemand.js 中提取的索引列表
            arr_2d: loading-x-anim SVG 中解析的二维数组

        Returns:
            ClientTransaction 实例
        """
        instance = cls.__new__(cls)
        instance.key_bytes = key_bytes
        instance.DEFAULT_ROW_INDEX = key_byte_indices[0]
        instance.DEFAULT_KEY_BYTES_INDICES = key_byte_indices[1:]
        instance.arr_2d = arr_2d
        instance.get_animation_key()
        return instance

    def get_key_bytes(self, home_page_response):
        element = home_page_response.select_one("[name='twitter-site-verification']")
        if not element:
            raise Exception("Couldn't get key from the page source")
        key = element.get("content")
        return list(base64.b64decode(bytes(key, 'utf-8')))

    def get_2d_array(self, home_page_response):
        frames = home_page_response.select("[id^='loading-x-anim']")
        self.arr_2d = [[int(x) for x in re.sub(r"[^\d]+", " ", item).strip().split()] for item in list(list(frames[self.key_bytes[5] % 4].children)[0].children)[1].get("d")[9:].split("C")]

    def solve(self, value, min_val, max_val, rounding: bool):
        result = value * (max_val-min_val) / 255 + min_val
        return math.floor(result) if rounding else round(result, 2)

    
    def animate(self, frames, target_time):
        
        from_color = [float(item) for item in [*frames[:3], 1]]
        
        to_color = [float(item) for item in [*frames[3:6], 1]]
        
        from_rotation = [0.0]
        
        to_rotation = [self.solve(float(frames[6]), 60.0, 360.0, True)]
        
        frames = frames[7:]
        
        curves = [self.solve(float(item), is_odd(counter), 1.0, False)
                  for counter, item in enumerate(frames)]
        
        cubic = Cubic(curves)
        
        val = cubic.get_value(target_time)
        
        color = interpolate(from_color, to_color, val)
        
        color = [value if value > 0 else 0 for value in color]
        
        rotation = interpolate(from_rotation, to_rotation, val)
        
        matrix = convert_rotation_to_matrix(rotation[0])
        str_arr = [format(round(value), 'x') for value in color[:-1]]
        for value in matrix:
            rounded = round(value, 2)
            if rounded < 0:
                rounded = -rounded
            hex_value = float_to_hex(rounded)
            str_arr.append(f"0{hex_value}".lower() if hex_value.startswith(
                ".") else hex_value if hex_value else '0')
        str_arr.extend(["0", "0"])
        animation_key = re.sub(r"[.-]", "", "".join(str_arr))
        return animation_key

    
    def get_animation_key(self):
        total_time = 4096
        row_index = self.key_bytes[self.DEFAULT_ROW_INDEX] % 16
        frame_time = reduce(lambda num1, num2: num1*num2,
                            [self.key_bytes[index] % 16 for index in self.DEFAULT_KEY_BYTES_INDICES])
        frame_row = self.arr_2d[row_index]
        target_time = float(frame_time) / total_time
        self.animation_key = self.animate(frame_row, target_time)

    
    def generate_transaction_id(self, method: str, path: str):
        
        time_now = math.floor((time.time() * 1000 - 1682924400 * 1000) / 1000)
        
        time_now_bytes = [(time_now >> (i * 8)) & 0xFF for i in range(4)]

        animation_key = self.animation_key or self.DEFAULT_ANIMATION_KEY
        
        hash_val = hashlib.sha256(f"{method}!{path}!{time_now}{self.DEFAULT_KEYWORD}{animation_key}".encode()).digest()
        
        hash_bytes = list(hash_val)
        
        random_num = random.randint(0, 255)
        
        bytes_arr = [*self.key_bytes, *time_now_bytes, *
                     hash_bytes[:16], self.ADDITIONAL_RANDOM_NUMBER]
        
        out = bytearray([random_num, *[item ^ random_num for item in bytes_arr]])
        
        return base64_encode(out).strip("=")
