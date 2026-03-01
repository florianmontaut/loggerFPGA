import numpy as np

import json
from PyQt6.QtCore import QThread,pyqtSignal,QByteArray,QTimer,QObject
from PyQt6.QtNetwork import QUdpSocket,QHostAddress
import socket
import numpy as np
import pathlib
import time

from ressources.CustomItems import FGPAconfigStruct

PATH=pathlib.Path(__file__).parent

##* repris du code de XSS+DMV à 95% *##
class acquisition_FPGA(QThread): # Classe acquisition_FPGA

    data_received = pyqtSignal(np.ndarray)  # Signal pour envoyer les données après réception
    status_changed = pyqtSignal(str)
    error_occurred = pyqtSignal(str)    # Signal pour les erreurs

    def __init__(self, parent=None):
        super(acquisition_FPGA, self).__init__()
        #Dummy config pour charger la vrai structure venant du JSON
        self.config=FGPAconfigStruct()
        self.config.fromJson(json_file='parametres_scope.json')
        self.setUdp()
        self.setChannels()
        #self.t_send=0
        self.t_recept=0
        #self.t_send_pre=0
        self.t_recept_pre=0
        self.data_read=False
        self.is_running = False
        self.n_readTrames=0 #32 readTrame à chaque acquisition du FPGA
        self.n_trames=0 #nombre d'acquisitions envoyées par le FPGA
        self.tramesDict={'b\'\\x80\\x04\'':['data',0],
                        'b\'\\x80\\x02\'' :['trigger',0]}
        #! essai pour couper le socket à la destruction de l'objet, ne semble pas fonctionner
        self.destroyed.connect(self.close)
        self.once=True
        self.readtimer = QTimer(self)
        self.readtimer.setSingleShot(False)
        self.readtimer.timeout.connect(self.read)


    def setUdp(self):
        self.port_msg   =    bytearray([0x80, 0x05, 0x55, 0xAA, 0x00, 0x00])
        self.start_msg  =    bytearray([0x80, 0x01, 0xAA, 0x55, 0x00, 0x00])
        self.trig_msg   =    bytearray([0x80, 0x02])
        self.read_msg   =    bytearray([0x80, 0x03, 0x55, 0x55, 0x00, 0x00])
        self.data_msg   =    bytearray([0x80, 0x04])
        self.stop_msg   =    bytearray([0x80, 0x06, 0xAA, 0xAA, 0x00, 0x00])
        self.config_msg =    bytearray([])
        self.data_8     =    bytearray([]) # tableau d'octets contenant les données à affich
        self.msg_frame  =    bytearray([]) # tableau d'octets de réception UDP
        
    def setChannels(self):

        self.frame = 0
        self.sd = self.config.n_words
        self.tempo = int(np.round((self.sd*self.config.divider/25e6)*1000+1,0))
        if self.config.n_ana_channels!=15:
            self.gains=[0.01761474609375 for val in self.config.channels_config]
            self.offsets=[0 for val in self.config.channels_config]
            #self.gains=[self.config.gains[val] for val in self.config.channels_config]
            #self.offsets=[self.config.offsets[val] for val in self.config.channels_config]
        else:
            self.gains=[1]*15
            self.offsets=[0]*15
        #self.config_msg = former_message_config(self.nombre_canaux,self.config_canaux,
        #self.diviseur,self.delai_acquisition,self.trig,self.trip,self.threshold)

    def read(self):

        if self.config.type_trigger==0 and not self.data_read:

            self.envoi_message_udp(self.start_msg)
            #self.t_send= time.time()
            #print(f'new cycle: {self.t_send-self.t_send_pre}')
            #self.t_send_pre=self.t_send
            #print(f'delta t emission: {self.t_send-self.t_send_pre} ; {self.read_msg}')
        if self.data_read:
            self.envoi_message_udp(self.read_msg) # envoi requête de lecture data

    def open(self):
        try:
            #création du socket au sein même de la fonction de façon à assurer la remise en route systématique de la fonction
            #si le socket est créer dans l'init, la déconnexion puis la reconnexion ne permet pas de se reconnecter systématiquement
            self.udp_socket_client = QUdpSocket()
            self.udp_socket_client.bind(QHostAddress(self.config.local_ip), self.config.local_port)
            #print(self.config.LOCAL_PORT,self.config.LOCAL_IP)
            self.udp_socket_client.readyRead.connect(lambda: self.reception_message_udp(1030))
            self.is_running = True # Tâche lancée
            QThread.msleep(100)
            self.envoi_message_udp_config_port(self.port_msg)
            QThread.msleep(100)
            #! maj maincontroller
            #print("envoi message config port")
            #envoi du message de configuration sous forme de tableau d'octets, formé par la méthode former_message_config
            #self.envoi_message_udp(self.config_msg_test)
            trame=self.former_message_config()
            self.envoi_message_udp(trame)
            self.status_changed.emit(f"{trame}")
            QThread.msleep(self.tempo)
            #! maj maincontroller
            #print("message de config envoyé")
            self.set_mode_acquisition(1) # mode acquisition infini

            #self.envoi_message_udp(self.start_msg)
            if self.mode_acq==0:
                self.frame_number=1 # mode acquisition unique
            else:
                self.frame_number=10**15 # mode acquisition infini #! mauvaise conditions d'entrée si -1
            # tant que la tâche de réception est active et tant que l'acquisition est active

            self.n_messsages = int(self.sd/512)
            if self.config.type_trigger==0:
                self.envoi_message_udp(self.start_msg)

        except Exception as e:
            pass
            #print(f"Erreur de communication:{e}")

        finally:
            pass
            #print("Fin")

    def extractData(self,data):
        """
        data_16 = list(self.unpackBytesArray(data,16)) # list permet de passer d'utiliser le générateur et ainsi récupérer les valeurs
        reshaped_data_16 = np.reshape(data_16,(-1, self.sd//self.config.N_ANA_CHANNELS)).T # // garantit que le résultat est un entier (tronqué vers l'entier inférieur)(self.sd//self.config.N_ANA_CHANNELS, self.config.N_ANA_CHANNELS))
        data_16_flipped = np.fliplr(reshaped_data_16)
        return data_16_flipped"""
        data_16 = np.frombuffer(data, dtype=">i2")  # big-endian unsigned 16
        # ou dtype=">i2" si signé
        data_16 = data_16.reshape((-1, self.sd//self.config.n_ana_channels))
        
                
        ones=np.ones(data_16.shape[1])
        gain=np.row_stack([ones*val for val in reversed(self.gains)])
        offset=np.row_stack([ones*val for val in reversed(self.offsets)])
        print(gain)
        data_16=data_16*gain+offset

        return np.fliplr(data_16.T)
        

    def stop(self):
        self.is_running = False
        self.data_read=False
        self.data_8=bytearray([])
        self.n_readTrames=0
        self.n_trames=0
        self.envoi_message_udp(self.stop_msg)
        self.close()

    def update(self,new_config):

        self.stop()
        self.setChannels(new_config)
        self.is_running = True
        self.open()


    def envoi_message_udp(self, message):

        b = QByteArray(message)
        self.udp_socket_client.writeDatagram(b.data(), QHostAddress(self.config.ip_fpga), self.config.remote_port_fpga)
        #self.udp_socket_client.close()

    def envoi_message_udp_config_port(self, message):
        b = QByteArray(message)
        self.udp_socket_client.writeDatagram(b.data(), QHostAddress(self.config.ip_fpga), self.config.target_port_fpga)


    def close(self):
        self.udp_socket_client.readyRead.disconnect()
        self.udp_socket_client.close()
        self.udp_socket_client.deleteLater()

    def reception_message_udp(self,size_octets): # méthode de réception de messages UDP

        #! actuellement perd la connexion au moindre défaut/packet loss
        try:
            if not self.data_read:
                datagram, host, port=self.udp_socket_client.readDatagram(6)
            else:
                datagram, host, port=self.udp_socket_client.readDatagram(size_octets)

            #on ignore les messages du multicast API
            if host.toString() != "224.0.0.251":
                header=datagram[:2]
                if header==self.data_msg:
                    self.data_read=True
                    #On ne récupère que les bits après les 6 premiers
                    self.data_8.extend(datagram[6:])
                    self.n_readTrames+=1
                    self.t_recept= time.time()
                    #self.status_changed.emit(f"En-tête: {datagram[0:6].hex()}")
                    #self.status_changed.emit(f"La suite: {datagram[6:10].hex()}")
                    #val=np.frombuffer(datagram[6:10], dtype=">i2")
                    #self.status_changed.emit(f"Ce qui vaut: {val} Type: {type(val)}")
                    #out=[hex[i:i+2] for i in range(0, len(hex), 2)]
                    #self.status_changed.emit(' '.join(out))
                                
                #? code suivant permet de lister et compter le nombre trame envoyé par le FGPA
                if str(header) not in list(self.tramesDict.keys()):
                    self.tramesDict[str(header)]=['New header',0]
                else:
                    self.tramesDict[str(header)][1]=self.tramesDict[str(header)][1]+1

                if header == self.trig_msg or self.n_readTrames >self.n_messsages-1:
                    self.data_read=True #! nécessaire pour ne pas perdre la première trame data

                    if len(self.data_8) > 0:
                        self.data_read=False

                        flipped_data= self.extractData(self.data_8)
                        self.data_received.emit(flipped_data)
                        self.data_8=bytearray([])
                        self.n_trames+=1
                        #self.status_changed.emit(f'{self.t_recept-self.t_recept_pre}')
                        self.t_recept_pre=self.t_recept
                        self.readtimer.start(self.tempo)
                        #QThread.msleep(self.tempo)
                    else:
                        self.read()
                    self.n_readTrames=0
                    

        except socket.timeout:
            pass
            #print('Timeout !')

    def former_message_config(self):

        div_high = int(np.fix(self.config.divider/256))
        div_low = int(self.config.divider - (div_high * 256))

        del_high = int(np.fix(self.config.delay/256))
        del_low = int(self.config.delay - (del_high * 256))
        # fix() permet de tronquer en ne gardant que la partie décimale,
        # on s'assure également de ne renvoyer qu'un octet avec int()
        trip = int.from_bytes(bytearray.fromhex(self.config.trip))
        trip_Hh = int(np.fix(trip/16777216))
        trip_Hl = int(np.fix((trip-trip_Hh*16777216)/65536))
        trip_Lh = int(np.fix((trip-trip_Hh*16777216-trip_Hl*65536)/256))
        trip_Ll = int(trip-trip_Hh*16777216-trip_Hl*65536-trip_Lh*256)

        if(self.config.trigger_thres < 0):
            threshold = 65536+self.config.trigger_thres
        else:
            threshold = self.config.trigger_thres
        threshold_high = int(np.fix(threshold/256))
        threshold_low =  int(threshold - (threshold_high * 256))
        try :

            ch_config=[0,0,0,0]
            ch_position=(1,1,0,0,3,3,2,2)
            if self.config.n_ana_channels==1:
                ch_config=[0,self.config.channels_config[0],0,0]
            elif self.config.n_ana_channels==15:
                ch_config[1]=15
            else:
                for ch_index,ch_val in enumerate(self.config.channels_config):

                    power=1-(ch_index+1)%2 # 16^1 si chanel impair et 16^0 si pair
                    ch_config[ch_position[ch_index]]+=ch_val*16**power

            config_msg = bytearray([0x80, 0x00,                                                            # entête trame réseau
                            0x55, 0xAA,
                            0x00, 0x1A,
                            0x00, self.config.n_ana_channels]
                        )+ bytearray(ch_config
                        )+ bytearray([0x00, 0x00,
                            0x00, 0x00,
                            div_high, div_low,                                                             # diviseur
                            0x00, 0x00,
                            del_high, del_low,                                                             # délai
                            0x00, 0x00,
                            0x00, self.config.type_trigger,                                                # type de trigger
                            trip_Lh, trip_Ll,
                            trip_Hh, trip_Hl,                                                              # masque de trip sur 4 octets
                            threshold_high, threshold_low])                                                # seuil de déclenchement

            #print(f"message config formé: {config_msg}")
            #! envoyer message au maincontroller
            return config_msg
        except Exception as e:
            #print(f"Erreur de formation du message de configuration: {e}")
            #! envoyer message au maincontroller
            return None


    def set_mode_acquisition(self,mode): # définir le mode d'acquisition en unique ou infini
        if mode ==0:
            self.mode_acq=0 # mode unique
        else:
            self.mode_acq=1 # mode infini

    @staticmethod
    def unpackBytesArray(data,bitlen):

        mask = (1 << bitlen) - 1
        for chunk in zip(*[iter(data)] * bitlen):
            n = int.from_bytes(chunk, 'big')#big endian
            a = []
            for i in range(8):
                a.append(n & mask)
                n >>= bitlen
            yield from reversed(a)

'''
def unpackBytesArray(data,bitlen):

    mask = (1 << bitlen) - 1
    for chunk in zip(*[iter(data)] * bitlen):
        n = int.from_bytes(chunk, 'big')#big endian
        a = []
        for i in range(8):
            a.append(n & mask)
            n >>= bitlen
        yield from reversed(a)


def extractData(data):

        data_16 = np.frombuffer(data, dtype=np.dtype(np.int16))  # big-endian unsigned 16
        # ou dtype=">i2" si signé
        data_16=data_16.reshape((-1, 512 // 2)).T
        return  np.fliplr(data_16)

'''