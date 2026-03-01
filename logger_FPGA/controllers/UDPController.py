import time
import numpy as np
from PyQt6.QtCore import QObject, pyqtSignal, QTimer, QThread,QByteArray,pyqtSlot
from PyQt6.QtNetwork import QUdpSocket, QHostAddress
from ressources import CustomItems

class acquisition_FPGA(QThread):

    data_received = pyqtSignal(np.ndarray)
    error_occurred = pyqtSignal(str)
    status_changed = pyqtSignal(str)  # optionnel

    REPLYTIMEOUTMS = 20
    MAXRETRY = 10
    BACKOFFSTARTMS = 200
    BACKOFFMAXMS = 3000

    def __init__(self, config:CustomItems.FGPAconfigStruct=None):

        super(acquisition_FPGA, self).__init__()

        if config is not None:
            self.setUDP(config)
        else:
            #! LA CONFIGURATION JSON N'EST JAMAIS CHARGEE ACTUELLEMENT (20/02)
            self.config = CustomItems.FGPAconfigStruct()
            self.setUDP()

        self.udpsocketclient: QUdpSocket | None = None
        self.isConnected = False

        # état transactionnel
        self.waitingreply = False
        self.rxseensincelasttx = False
        self.retrycount = 0

        # reconnexion
        self.backoffms = self.BACKOFFSTARTMS
        self.reconnecttimer = QTimer(self)
        self.reconnecttimer.setSingleShot(True)
        self.reconnecttimer.timeout.connect(self.doReconnect)

        # timer timeout 20ms
        self.replytimer = QTimer(self)
        self.replytimer.setSingleShot(False)
        self.replytimer.timeout.connect(self.onReplyTimeout)

        # buffers
        self.data_read = False
        self.data_8 = bytearray()
        self.n_readTrames = 0
        self.ntrames = 0
        self.cpt_time_out=0

        #messages
        self.port_msg   =    bytearray([0x80, 0x05, 0x55, 0xAA, 0x00, 0x00])
        self.start_msg  =    bytearray([0x80, 0x01, 0xAA, 0x55, 0x00, 0x00])
        self.trig_msg   =    bytearray([0x80, 0x02])
        self.read_msg   =    bytearray([0x80, 0x03, 0x55, 0x55, 0x00, 0x00])
        self.data_msg   =    bytearray([0x80, 0x04])
        self.stop_msg   =    bytearray([0x80, 0x06, 0xAA, 0xAA, 0x00, 0x00])
        self.config_msg =    bytearray([])
        self.data_8     =    bytearray([]) # tableau d'octets contenant les données à afficher

    def setUDP(self,config=None):

        if config is not None:
            self.config = config

        #self.config.fromJson(json_file='parametres_scope.json')
        self.setChannels()
        self.frame = 0
        self.sd = self.config.n_words
        self.tempo = int(np.round((self.sd*self.config.divider/25e6)*1000+1,0))

    def setChannels(self,gains=None,offsets=None):
        #! REVOIR LA GESTION DES GAINS !
        if self.config.n_ana_channels!=15:
            self.gains=[1]*15
            self.offsets=[0]*15
            #self.gains=[self.config.gains[val] for val in self.config.channels_config]
            #self.offsets=[self.config.offsets[val] for val in self.config.channels_config]
        else:
            self.gains=[1]*15
            self.offsets=[0]*15

    def former_message_config(self):

        div_high = int(np.fix(self.config.divider/256))
        div_low = int(self.config.divider - (div_high * 256))
        del_high = int(np.fix(self.config.delay/256))
        del_low = int(self.config.delay - (del_high * 256))
        # fix() permet de tronquer en ne gardant que la partie décimale,
        # on s'assure également de ne renvoyer qu'un octet avec int()
        trip=int.from_bytes(bytearray.fromhex(self.config.trip))
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
            ch_position=(1,1,0,0,3,3,2,2) # '0xAA BB CC DD' => 0x'BB AA DD CC'
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
            return config_msg
        except Exception as e:
            #print(f"Erreur de formation du message de configuration: {e}")
            #! envoyer message au maincontroller
            return e

    def extractData(self,data):

        data_16 = np.frombuffer(data, dtype=">i2")  # big-endian unsigned 16
        print(f'Ligne 142 UDP controller: {self.sd//self.config.n_ana_channels}/ shape {data_16.shape}')
        # ou dtype=">i2" si signé
        if data_16.shape[0] != self.config.n_words:
            return
        data_16 = data_16.reshape((-1, self.sd//self.config.n_ana_channels))

        #application du gain, en pratique l'offset devrait rester nul car les mesures
        #sont en virgule fixe (le FPGA décale de 14bits et applique sont gain de normalisation)
        ones=np.ones(data_16.shape[1])
        #! change le format de la matrice !
        gain=np.row_stack([ones*val for val in reversed(self.gains)])
        offset=np.row_stack([ones*val for val in reversed(self.offsets)])

        data_16=data_16*gain+offset
        print(f'Ligne 142 UDP controller: {self.sd//self.config.n_ana_channels}/ shape {data_16.shape}')
        return np.fliplr(data_16.T)

# ---------------- lifecycle ----------------

    def createAndBindSocket(self):

        if self.udpsocketclient is not None:
            self.destroySocket()

        self.udpsocketclient = QUdpSocket(self)  # parentage OK 12
        self.udpsocketclient.readyRead.connect(self.onReadyRead)
        self.status_changed.emit(f'CreateAndBindSocket')
        ok = self.udpsocketclient.bind(QHostAddress(self.config.local_ip), self.config.local_port)
        if not ok:
            # Option si "address already in use":
            # ok = self.udpsocketclient.bind(QHostAddress(self.config.LOCALIP), self.config.LOCALPORT,
            #      QUdpSocket.BindMode(QUdpSocket.ShareAddress | QUdpSocket.ReuseAddressHint))
            # 78
            self.error_occurred.emit(f"bind() failed: {self.udpsocketclient.errorString()}")
            self.scheduleReconnect("bind failed")
            self.udpsocketclient = None

    def open(self):
        """Ouvre (ou ré-ouvre) le lien applicatif."""
        if self.config is None:
            return
        self.isConnected = True
        self.retrycount = 0
        self.backoffms = self.BACKOFFSTARTMS
        self.createAndBindSocket()
        if self.udpsocketclient is None:
            return

        self.status_changed.emit("Connected")
        self.handshake()

    def close(self):
        """Arrêt propre."""
        self.isConnected = False
        self.replytimer.stop()
        self.reconnecttimer.stop()
        self.destroySocket()
        self.status_changed.emit("Disconnected")

    def destroySocket(self):
        if self.udpsocketclient is None:
            return
        try:
            self.udpsocketclient.close()
        finally:
            # deleteLater recommandé pour QObject si events pending 62
            self.udpsocketclient.deleteLater()
            self.udpsocketclient = None

    # ---------------- handshake (non bloquant) ----------------
    # (remplace QThread.msleep, évite de bloquer l'event loop)

    def handshake(self):
        # step1: config port
        self.sendNoWait(self.port_msg, port=self.config.target_port_fpga)
        QTimer.singleShot(100, self.handshakeStepTwo)

    def handshakeStepTwo(self):
        if not self.isConnected or self.udpsocketclient is None:
            return
        # step2: envoi config
        trame=self.former_message_config()

        self.sendNoWait(trame)  # si tu attends un ACK, sinon _sendnowait
        QTimer.singleShot(self.tempo, self.handshakeStepThree)

    def handshakeStepThree(self):
        if not self.isConnected or self.udpsocketclient is None:
            return
        self.setModeAcquisition(1)
        self.n_messsages = int(self.sd / 512)

        # dans ton cas : FPGA répond toujours <20ms, donc on peut "expect reply"
        if self.config.type_trigger == 0:
            self.sendExpectReply(self.start_msg,5000)
        else:
            # en trigger interne, tu peux envoyer un read périodique/heartbeat
            self.sendExpectReply(self.read_msg,200)
            #self.status_changed.emit(f'Read !')

    # ---------------- envoi + timeout 20ms ----------------

    def sendNoWait(self, message: bytes | bytearray, port: int=None):
        if self.udpsocketclient is None:
            return
        if port is None:
            port=self.config.remote_port_fpga
        b = QByteArray(message)
        self.udpsocketclient.writeDatagram(b.data(), QHostAddress(self.config.ip_fpga), port)

    def sendExpectReply(self, message: bytes | bytearray,
                        timeOut: int = REPLYTIMEOUTMS,
                        port: int | None = None):
        """envoie puis démarre une fenêtre d'attente de 20ms."""
        if self.udpsocketclient is None:
            return
        if port is None:
            port=self.config.remote_port_fpga
        self.waitingreply = True
        self.rx_seensincelasttx = False
        # envoi standard (REMOTEPORTFPGA)
        b = QByteArray(message)
        self.udpsocketclient.writeDatagram(b.data(), QHostAddress(self.config.ip_fpga), port)
        #self.udpsocketclient.writeDatagram(bytes(message), QHostAddress(self.config.ip_fpga), port)
        # démarre timeout, par défaut 20ms
        self.replytimer.start(timeOut)

    def onReplyTimeout(self):
        """Aucun paquet reçu sous TimeOut ms après un envoi 'expect reply'."""
        self.cpt_time_out+=1
        self.status_changed.emit(f'Nombre de timeout: {self.cpt_time_out}')
        if not self.isConnected or not self.waitingreply:
            return

        if self.rxseensincelasttx:
            # finalement reçu, on clôt
            self.waitingreply = False
            self.retrycount = 0
            return

        if self.retrycount < self.MAXRETRY:
            self.retrycount += 1
            # on retente un READ (heartbeat) : puisque tu confirmes réponse toujours <20ms
            self.sendExpectReply(self.start_msg,1000)
            self.sendExpectReply(self.read_msg)
            return

        # retries épuisés => reconnexion
        self.waitingreply = False
        self.retrycount = 0
        self.scheduleReconnect("No reply within 20ms (after retries)")

    # ---------------- RX: lire tous les datagrams ----------------

    def onReadyRead(self):
        if not self.isConnected or self.udpsocketclient is None:
            return

        self.rxseensincelasttx = True
        cpt=0
        # self.status_changed.emit('NEW LOOOOOOp')
        # Lire tous les datagrammes en attente 13
        while self.udpsocketclient.hasPendingDatagrams():
            #self.status_changed.emit(f'{self.udpsocketclient.pendingDatagramSize()}')
            datagram, host, port = self.udpsocketclient.readDatagram(1030)
            if host.toString() == "224.0.0.251":
                continue

            cpt+=1
            self.processDatagram(datagram)


        # stop le timeout si on attendait
        if self.waitingreply:
            self.replytimer.stop()
            self.waitingreply = False
            self.retrycount = 0

    def processDatagram(self, datagram: bytes):
        header = datagram[:2]

        if header == self.data_msg:
            self.data_read = True
            self.data_8.extend(datagram[6:])
            self.n_readTrames += 1
        #self.status_changed.emit(f'Data {self.n_readTrames} len: {len(self.data_8)}')
        if header == self.trig_msg or self.n_readTrames > self.n_messsages - 1:
            if len(self.data_8) > 0:
                flippeddata = self.extractData(self.data_8)
                if flippeddata is not None:
                    self.data_received.emit(flippeddata)
                self.sendExpectReply(self.start_msg)

            # reset cycle
            self.data_8 = bytearray()
            self.n_readTrames = 0
            # heartbeat/read suivant -> attendu <20ms
            self.sendExpectReply(self.read_msg)

    # ---------------- reconnexion ----------------

    def scheduleReconnect(self, reason: str):
        if self.reconnecttimer.isActive():
            return

        self.status_changed.emit("Reconnecting")
        self.error_occurred.emit(f"[RECONNECT] {reason} (backoff={self.backoffms}ms)")

        self.replytimer.stop()
        self.destroySocket()

        self.reconnecttimer.start(self.backoffms)
        self.backoffms = min(self.backoffms * 2, self.BACKOFFMAXMS)

    def doReconnect(self):
        if not self.isConnected:
            return
        self.open()


    def setModeAcquisition(self,mode): # définir le mode d'acquisition en unique ou infini
        if mode ==0:
            self.mode_acq=0 # mode unique
        else:
            self.mode_acq=1 # mode infini



if __name__ == '__main__':
    test=acquisition_FPGA()
    test.data_received.connect(lambda x: print(x))
    test.FPGAcom.open()
