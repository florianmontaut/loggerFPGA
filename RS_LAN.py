
from RsInstrument import RsInstrument
import pyvisa

# Connexion TCP/IP
instr = RsInstrument('TCPIP::192.168.0.30::137::SOCKET', True, True, "SelectVisa='socket'")

# Vérification instrument
print(instr.query("*IDN?"))

# Démarrer une mesure et récupérer la trace
instr.write("INIT:IMM;*WAI")
trace = instr.query("TRAC? TRACE1")

print(trace)
'''
if __name__ == '__main__':
          rm2 = pyvisa.ResourceManager()
          resources = rm2.list_resources('?*')
          print(resources)
          my_instrument = rm2.open_resource('VICP::192.168.0.30::INSTR')
          print(my_instrument.query('*IDN?'))'''
'''
from RsInstrument import *
# Replace '192.168.1.100' with the IP address of your oscilloscope
instr = RsInstrument('TCPIP::192.168.0.30::INSTR')
# Retrieve the instrument's identification string
idn_string = instr.query('*IDN?')
print(f'Connected to: {idn_string}')'''