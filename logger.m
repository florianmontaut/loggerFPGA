
% données enregistrables :

%  voies analogiques           voies logiques
%    0  V_HV                   0  K_HV
%    1  I_HV                   1  K_PRE
%    2  V_PH1_INV1             2  nu
%    3  I_PH1_INV1             3  nu
%    4  V_PH1_INV2             4  nu
%    5  I_PH1_INV2             5  nu
%    6  V_PH1_INV1 RMS         6  nu
%    7  I_PH1_INV1 RMS         7  nu
%    8  V_PH1_INV2 RMS         8  nu
%    9  I_PH1_INV2 RMS         9  nu
%   10  TEMP_AMB PLS           10 nu
%   11  INV_MODUL_A            11 nu
%   12  INV_MODUL_B            12 nu
%   13  INV_FREQ_A             13 nu
%   14  INV_FREQ_B             14 nu
%   15  données logiques       15 nu

% configuration des canaux 1 à 15 (1: un signal, 2: deux signaux, 4: quatre signaux, 8: huit signaux, 15: voies logiques)
chn = 1;

% sélection des voies de mesures analogiques 0 à 14
sig = [5 -0 -0 -0 -0 -0 -0 -0];

% diviseur 1 à 65535  (fréquence echantillonnage = 25 MHz/div)
%     1  25.00 MHz
%    25   1.00 MHz
%    28 892.86 kHz (horloge ADC)
%   500  50.00 kHz
%  1200  20.83 kHz (période Katium)
%  5000   5.00 kHz
% 25000   1.00 kHz
% 62500 400.00 Hz
div = 20;

% délai 0 à 65536
del = 5000;

% trigger (0: auto, 1: disjonction 2: >seuil, 4: <seuil)
trig = 0;

% masque des DJ 0x00000000 à 0xFFFFFFFF
trip = 0x00010000;

% seuil -32768 à 32767 (seuil sur la voie de mesure 0)
thres = -553; % V_LEAK -20V

% affichage des mesures 0 ou 1
pl = 1;

% enregistrement des mesures 0 ou 1
wr = 0;

% nombre max d'aquisitions (inf pour infini)
frame_nb = inf;
% frame_nb = 1;

% prefix pour les noms de fichiers
pre = "enr";

% nom des voies de mesure (pour les enregistrements)
ch_name = {'_V_HV_'; '_I_HV_'; '_V_PH1_INV1_'; '_I_PH1_INV1_'; '_V_PH1_INV2_'; '_I_PH1_INV2_'; '_V_PH1_INV1_RMS_';'_I_PH1_INV1_RMS_';
           '_V_PH1_INV2_RMS_'; '_I_PH1_INV2_RMS_'; '_TEMP_AMB PLS_'; '_INV_MODUL_A_'; '_INV_MODUL_B_'; '_INV_FREQ_A_'; '_INV_FREQ_B_'; ' '};

% gain applicable (pour les enregistrements)
ch_gain = [100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 0];

% adresse ip du FPGA
ip = '172.16.0.1';

%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%

%  Ne pas modifier le reste du fichier

%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%

if chn == 15  % mode logique
  sig = [15 -0 -0 -0 -0 -0 -0 -0];
  nch = 1;
else
  nch = chn;
endif

sd = 16384; % nombre de mots de 16 bits dans une trame de données

tempo = sd*div/25e6+1e-3;

div_h = fix(div/256);
div_l = div-div_h*256;

del_h = fix(del/256);
del_l = del-del_h*256;

trip_Hh = fix(trip/16777216);
trip_Hl = fix((trip-trip_Hh*16777216)/65536);
trip_Lh = fix((trip-trip_Hh*16777216-trip_Hl*65536)/256);
trip_Ll = trip-trip_Hh*16777216-trip_Hl*65536-trip_Lh*256;

if thres < 0
  thres = 65536+thres;
endif

thres_h = fix(thres/256);
thres_l = thres-thres_h*256;

% selection du port UDP et de l'IP du PC de commande (trame à envoyer sur le port UDP 9)
port_msg = uint8([0x80 0x05 0x55 0xAA 0x00 0x00]);

% configuration du logger
conf_msg = uint8([0x80,              0x00,              ... % entête trame reseau
                  0x55,              0xAA,              ...
                  0x00,              0x1A,              ...
                  0x00,              nch,               ... % nb canaux
                  16*sig(4)+sig(3),  16*sig(2)+sig(1),  ... % selection des signaux
                  16*sig(8)+sig(7),  16*sig(6)+sig(5),  ...
                  0x00,              0x00,              ...
                  0x00,              0x00,              ...
                  div_h,             div_l,             ... % diviseur
                  0x00,              0x00,              ...
                  del_h,             del_l,             ... % délai
                  0x00,              0x00,              ...
                  0x00,              trig,              ... % trigger
                  trip_Lh,           trip_Ll,           ... % mask disjonction
                  trip_Hh,           trip_Hl,           ...
                  thres_h,           thres_l]);             % seuil

% lancement de l'enregistrement
start_msg = uint8([0x80 0x01 0xAA 0x55 0x00 0x00]);
% trame indiquent que le logger est déclenché
trig_msg = uint8([0x80 0x02]);
% demande de données
read_msg = uint8([0x80 0x03 0x55 0x55 0x00 0x00]);
% trame de données
data_msg = uint8([0x80 0x04]);
% arrêt du logger
stop_msg = uint8([0x80 0x06 0xAA 0xAA 0x00 0x00]);

data_8 = uint8([]);
frame = 0;
br = 0;
err = 0;
stop = false;

if exist('udp_com', 'var')
  udp_close(udp_com)
endif

s = dos(cstrcat('.\arp-ping.exe -n 1 ', ip));
if s
  disp('')
  disp('   Communication Error')
  disp('')
  return
endif

if pl == 1
  if ~exist('fig') || ~ishghandle(fig)
    fig = figure('position', [1200 400 700 500], 'buttondownfcn', 'stop = true;');
    toolbar
  endif
endif

udp_com = udp(ip, 9, 'localport', 2064);
pause(100e-3)
udp_write(udp_com, port_msg);
udp_close(udp_com)

udp_com = udp(ip, 2064, 'localport', 2064);
pause(100e-3)
udp_write(udp_com, conf_msg);
pause(tempo)

tic
while length(kbhit(1)) == 0 && frame < frame_nb && ~stop

  if trig == 0
    udp_write(udp_com, start_msg);
  endif

  start = false;
  do
    [msg, msg_len] = udp_read(udp_com, 6, 2000);
    if msg_len != 0
      if msg(1) == trig_msg(1) && msg(2) == trig_msg(2)
        start = true;
      endif
    endif
  until start

  udp_write(udp_com, read_msg);

  index = sd/512;
  start = false;
  do
    [msg, msg_len] = udp_read(udp_com, 1030, 20);
    if msg_len == 0 && start
      break
    elseif msg_len != 0
      if msg(1) == data_msg(1) && msg(2) == data_msg(2)
        start = true;
        data_8(end+1:end+msg_len-6) = msg(7:msg_len);
        index--;
      endif
    endif
  until index == 0

  frame++;

  if index > 0
    frame
    index
    err++;
  else
    data_16 = typecast(uint16(data_8(1:2:length(data_8)-1))*256+uint16(data_8(2:2:length(data_8))), 'int16');
    data_16 = fliplr(reshape(data_16, sd/nch, nch));
    if sig(nch) == 15
      data_bin = dec2bin(data_16(:, end), 16);
      log = [bin2dec(data_bin(:, 16))/2, 1+bin2dec(data_bin(:, 15))/2, 2+bin2dec(data_bin(:, 14))/2, 3+bin2dec(data_bin(:, 13))/2, ...
           4+bin2dec(data_bin(:, 12))/2, 5+bin2dec(data_bin(:, 11))/2, 6+bin2dec(data_bin(:, 10))/2, 7+bin2dec(data_bin(:, 9))/2, ...
           8+bin2dec(data_bin(:, 8))/2, 9+bin2dec(data_bin(:, 7))/2, 10+bin2dec(data_bin(:, 6))/2, 11+bin2dec(data_bin(:, 5))/2, ...
           12+bin2dec(data_bin(:, 4))/2, 13+bin2dec(data_bin(:, 3))/2, 14+bin2dec(data_bin(:, 2))/2, 15+bin2dec(data_bin(:, 1))/2];
      if chn != 1
        data = double(data_16)(:, 1:end-1)/16384;
      endif
    else
      data = double(data_16)/16384;
    endif

    if pl == 1
       cla(gca, 'reset')
      if chn == 15
        img = subplot(1, 1, 1);
        stairs(log)
        set(img,'Position',[0.05, 0.0, .9, 0.95])
        yticks(0:15)
        ylim([-.5, 16])
        xticks([0 .25 .5 .75 1]*sd)
        xlim([0, sd])
      else
        if sig(nch) == 15
          img = subplot(2, 1, 2);
          stairs(log)
          set(img,'Position',[0.05, 0.0, .9, 0.35])
          yticks(0:15)
          ylim([-.5, 16])
          xticks([0 .25 .5 .75 1]*sd/nch)
          xlim([0, sd/nch])
          grid
          img = subplot(2, 1, 1);
          npl=nch-1;
        else
          img = subplot(1, 1, 1);
          npl=nch;
        endif
        plot(data.*ch_gain(sig(1:npl)+1))
        if sig(nch) == 15
          set(img,'Position',[0.05, 0.4, .9, 0.55])
        else
          set(img,'Position',[0.05, 0.0, .9, 0.95])
        endif
        ylim([-1, 1]*(floor(max(abs(ch_gain(sig(1:npl)+1)))/100)+1)*100)
        xticks([0 .25 .5 .75 1]*sd/nch)
        xlim([0, sd/chn])
      endif
      grid
      title(sprintf('%d  -  %.2f Mo', frame, frame*sd/1048576))
    endif

    if wr == 1
      if ~exist('fnum')
        fnum = 1;
      else
        fnum++;
      endif;
      if chn != 15
        if chn == 1
          f_dat = strcat(pre, char(ch_name(sig(1)+1)), sprintf('div_%d_%d.dat', div, fnum));
        elseif chn == 2
          f_dat = strcat(char(ch_name(sig(1)+1)), char(ch_name(sig(2)+1)), sprintf('div_%d_%d.dat', div, fnum));
        elseif chn == 4
          f_dat = strcat(pre, char(ch_name(sig(1)+1)), char(ch_name(sig(2)+1)), char(ch_name(sig(3)+1)), ...
                         char(ch_name(sig(4)+1)), sprintf('div_%d_%d.dat', div, fnum));
        elseif chn == 8
          f_dat = strcat(pre, char(ch_name(sig(1)+1)), char(ch_name(sig(2)+1)), char(ch_name(sig(3)+1)), ...
                         char(ch_name(sig(4)+1)), char(ch_name(sig(5)+1)), char(ch_name(sig(6)+1)), ...
                         char(ch_name(sig(7)+1)), char(ch_name(sig(8)+1)), sprintf('div_%d_%d.dat', div, fnum));
        endif
        for i = 1:size(data)(2)
          data(:, i) = data(:, i)*ch_gain(sig(i)+1);
        endfor
        save('-binary', f_dat, 'data')
      endif
      if sig(nch) == 15
        log = [bin2dec(data_bin(:, 16)), bin2dec(data_bin(:, 15)), bin2dec(data_bin(:, 14)), bin2dec(data_bin(:, 13)), ...
               bin2dec(data_bin(:, 12)), bin2dec(data_bin(:, 11)), bin2dec(data_bin(:, 10)), bin2dec(data_bin(:, 9)), ...
               bin2dec(data_bin(:, 8)), bin2dec(data_bin(:, 7)), bin2dec(data_bin(:, 6)), bin2dec(data_bin(:, 5)), ...
               bin2dec(data_bin(:, 4)), bin2dec(data_bin(:, 3)), bin2dec(data_bin(:, 1)), bin2dec(data_bin(:, 1))];
        f_log = strcat(pre, sprintf('Logic_div_%d_%d.dat', div, fnum));
        save('-binary', f_log, 'log')
      endif
    endif
  endif

  data_8 = uint8([]);
  pause(tempo)

endwhile
toc

disp('')
frame
err
disp('')

udp_write(udp_com, stop_msg);
udp_close(udp_com)