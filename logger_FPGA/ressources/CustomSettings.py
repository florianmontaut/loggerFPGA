params={"Import settings":
            [
                {"name":"Remove old viewer data when importing new file","type":"bool","value":False},
                {"name":"Remove overrange channels","type":"bool","value":True},
                {"name":"Auto filter","type":"bool","value":False},
                {"name":"Use the file datetime to synchronize log files" ,"type":"bool","value":False},
                {"name":"Downsample at import","type":"group","enabled":False,"children":
                    [
                        {"name":"Active","type":"bool","value":True,"enabled":False},
                        {"name":"Downsampling factor","type":"int","value": 10,"limits":[2,None],"enabled":False},
                        {"name":"Downsampling type","type":"list","value":"peak","limits":["subsample","mean","peak"],"enabled":False},
                        {"name":"Downsampling threshold","type":"int","value": 10,"limits":[2,None],"enabled":False}
                    ]
                },
                {"name":"File import setting","type":"group","enabled":True,"children":
                    [
                        {"name":"Use latest files as working folder","type":"bool","value": True},
                        {"name":"Set working folder","type":"file","value": "","enabled":True,'fileMode':'Directory'},
                    ]
                }
            ],
        "Export settings":
            [
                {"name":"Export raw channels","type":"bool","value":True},
                {"name":"Export disabled channels","type":"bool","value":True},
                {"name":"Export modified channels","type":"bool","value":True}
            ],
        "Filter settings":
            [
                {"name":"Cut-off frequency","type":"float","value": 0.003,"limits":[0.00001,None]}
            ],
        "Graph settings":
            [   
                {"name":"X axis","type":"group","children":
                    [
                    {"name":"X axis title","type":"str","value":"Temps"},
                    {"name":"X axis unit","type":"str","value":"s"},
                    {"name":"X major tick","type":"float","value":"1200"},
                    {"name":"X minor tick","type":"float","value":"300"}
                    ]
                },
                {"name":"Y axis","type":"group","children":
                    [
                    {"name":"Y axis title","type":"str","value":"Temperature"},
                    {"name":"Y axis unit","type":"str","value":"°C"},
                    {"name":"Y major tick","type":"float","value":"10"},
                    {"name":"Y minor tick","type":"float","value":"2"}
                    ]
                },
                {"name":"Update axis when signal selected","type":"bool","value":"True"},
                {"name":"Downsample","type":"group","children":
                    [
                        {"name":"Active","type":"bool","value":True},
                        {"name":"Downsampling factor","type":"int","value": 10,"limits":[2,None]},
                        {"name":"Downsampling type","type":"list","value":"peak","limits":["subsample","mean","peak"]}
                    ]
                },
                {"name":"Appearance","type":"group","children":
                    [
                    {"name":"Graph Background color","type":"color","value":"#000000"},
                    {"name":"Dark mode","type":"bool","value":False}
                    ]
                }
            ]
        }

'''
Attributs des différentes classes correspondantes:

#ImportController
Import settings:
    """
    "remove_old_graph"  :  "Remove old viewer data when importing new file"
    "remove_overrange"  :  "Remove overrange channels"
    "auto_filter"       :  "Auto filter"
    "datetime_active"   :  "Use the file datetime to synchronize log files"
    "downsample_signals":  ("Downsample at import","Active")
    "downsample_ratio"  :  ("Downsample at import","Downsampling factor")
    "downsample_type"   :  ("Downsample at import","Downsampling type")
    "downsample_thres"  :  ("Downsampling threshold")
    """

#ExportController
Export settings:
    """
    "export_raw"        :   "Export raw channels"
    "export_disabled"   :   "Export disabled channels"
    "export_modified"   :   "Export modified channels"
    """

#MainController
Filter settings:
    """
    "filter_freq"       :   "Cut-off frequency"
    """

#View
Graph settings:
    """
    "X_title" :             "X axis title"
    "X_unit" :              "X axis unit"
    "Y_title" :             "Y axis title"
    "Y_unit" :              "Y axis unit"
    "update_selected" :     "Update axis when signal selected"
    "downsample" :          ("Downsample","Active")
    "downsample_ratio" :    ("Downsample","Downsampling factor")
    "downsample_type" :     ("Downsample","Downsampling type")
    """

'''