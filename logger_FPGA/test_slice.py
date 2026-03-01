import numpy as np
import pathlib


a=[1,2,3,4,5,6,8]
b=a[0:len(a)]
c=[2,3]
d=a[4:4+len(c)]


def unpackBytesArray(data,bitlen):
        mask = (1 << bitlen) - 1
        for chunk in zip(*[iter(data)] * bitlen):
            
            n = int.from_bytes(chunk, 'big')#big endian
            print(n)
            a = []
            for i in range(8):
                a.append(n & mask)
                n >>= bitlen
            print(f'a:{a}')
            yield from reversed(a)


a=bytearray([  0xFF,0xFF,
                0x55,0xAA,
                0x00,0x1A,
                0x00,0x04,
                0x83,0x10,
                0x00,0x00,
                0x00,0x00,
                0x00,0x00,
                0x00,0x1C, 
                0x00,0x00,
                0x00,0x00,
                0x00,0x00, 
                0x00,0x00,
                0x00,0x00,
                0x01,0x00,
                0x00,0x00])

reshaped_data_16 = np.reshape(list(unpackBytesArray(a,16)),(-1, 16//2)).T
final=np.fliplr(reshaped_data_16)
print(list(unpackBytesArray(a,16)))
print(reshaped_data_16)
print(final)



PATH=pathlib.Path(__file__).parent

print(PATH.absolute(),str(PATH.absolute()))