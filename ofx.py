#ofx.py
# http://sites.google.com/site/pocketsense/

# Original version: by Steve Dunham

# History
# ---------
# 2009: TFB @ "TheFinanceBuff.com"

# Feb-2010*rlc (pocketsense) 
#       - Modified use of the code (call methods, etc.). Use getdata.py to call this routine for specific accounts.
#       - Added scrubber module to clean up known issues with statements. (currently only Discover)
#       - Modified sites structure to include minimum download period
#       - Moved site, stock, fund and user-defined parameters to sites.dat and implemented a parser
#       - Perform a bit of validation on output files before sending to Money
#       - Substantial script edits, so that users shouldn't have a need to debug/edit code.
# 07-May-2010*rlc
#   - Try not to bomb if the server connection fails or times out and set return STATUS accordinging
# 10-Sep-2010*rlc
#   - Added timeout to https call
# 12-Oct-2010*rlc
#   - Fixed bug w/ '&' character in SiteName entries
# 30-Nov-2010*rlc
#   - Catch missing <SECLIST> in statements when a <INVPOSLIST> section exists.  This appears to be a required
#     pairing, but sometimes Vanguard to omits the SECLIST when there are no transactions for the period.
#     Money bombs royally when it happens...
# 01-May-2011*rlc
#   - Replaced check for (<INVPOSLIST> & <SECLIST>) pair with a check for (<INVPOS> & <SECLIST>)
# 18Aug2012*rlc
#   - Added support for OFX version 103 and ClientUID parameter.  The version is defined in sites.dat for a 
#     specific site entry, and the ClientUID is auto-generated for the client and saved in sites.dat
# 20Aug2012*rlc
#   - Changed method used for interval selection (default passed by getdata)
# 15Mar2013*rlc
#   - Added sanity check for <SEVERITY>ERROR code in server reply
# 11Feb2015*rlc
#   - Added support for mapping bank accounts to multiple Money accounts
#     Account "versions" are defined by adding a ":xx" suffix in Setup.py.  
#     The appended "version" is stripped from the account# before passing 
#     to the bank, but is used when sending the results to Money.  
# 11Mar2017*rlc
#   - Changed httplib requests to manually populate headers, due to Discover quackery
#   - Add support for OFX 2.x (xml) exchange while responding to Discover issue
#   - See discussions circa Mar-2017, and contributions from Andrew Dingwall
#   - Add support for site and user specific ClientUID
# 17May2017*rlc
#   - Add V1 POST method as a fallback, for servers that don't like the newer header
# 13Jul2017*rlc
#   - Add support for session cookies in response to change @ Vanguard 
# 24Aug2018*rlc
#   - Remove CLTCOOKIE from request.  Not supported by Money 2005+ or Quicken
# 19Nov2019*rlc
#   - Add site delay option
# 15Feb2021*rlc
#   - add support for site-specific skipZeroTrans option
#   - add support for the following site parameters: dtacctup, useragent, clientuid
# 20Feb2021*rlc
#   - changed http requests to use the Requests pkg rather than httplib
#     unresolved issues were happening for USAA, which uses an Incapsula gateway, 
#     and requests (pkg) correctly negotiated the connection, where httplib didn't.
#18Aug2021*rlc
#   - add Accept: application/x-ofx to request header.  Now required by Citi.
#30May2023*rlc
#   - encode requests response to ascii
#19Jun2023*rlc
#   - add logging

import time, os, sys, urllib2, glob, random, re
import requests, collections
import getpass, scrubber, site_cfg, uuid
from control2 import *
from rlib1 import *

if Debug:
    import traceback

#define some function pointers
join = str.join
argv = sys.argv

#define some globals
userdat = site_cfg.site_cfg()
                                               
class OFXClient:
    #Encapsulate an ofx client, site is a dict containg site configuration
    def __init__(self, site, user, password):
        global log
        log = logging.getLogger('root')
        
        self.password = password
        self.status = True
        self.user = user
        self.site = site
        self.ofxver = FieldVal(site,"ofxver")
        self.url = FieldVal(self.site,"url")
        self.dtacctup = FieldVal(self.site,"dtacctup") or '19700101'
        self.clientuid =  FieldVal(self.site,"clientuid")  #<optional> user-entered clientUID for site
        #if the user hasn't defined a clientUID and ofxVer>102, auto-create and save
        if self.clientuid is None and int(self.ofxver) > 102:  
            self.clientuid = clientUID(self.url, self.user)
        self.useragent  =  FieldVal(self.site,"useragent")
        
        #example: url='https://test.ofx.com/my/script'
        prefix, path = urllib2.splittype(self.url)
        #path='//test.ofx.com/my/script';  Host= 'test.ofx.com' ; Selector= '/my/script'
        self.urlHost, self.urlSelector = urllib2.splithost(path)
        if Debug: 
            log.debug('urlHost    :' + self.urlHost)
            log.debug('urlSelector:' + self.urlSelector)
        self.cookie = 3

    def _cookie(self):
        self.cookie += 1
        return str(self.cookie)

    #Generate signon message
    def _signOn(self):
        site = self.site
        ver  = self.ofxver
        
        clientuid=''
        if int(ver) > 102: 
            #include clientuid if version=103+, otherwise the server may reject the request
            clientuid = OfxField("CLIENTUID", self.clientuid, ver)
        
        fidata = [OfxField("ORG",FieldVal(site,"fiorg"), ver)]
        fidata += [OfxField("FID",FieldVal(site,"fid"), ver)]
        rtn = OfxTag("SIGNONMSGSRQV1",
                OfxTag("SONRQ",
                #OfxField("DTCLIENT",dateTimeStr(utc=True, tz=True), ver),
                OfxField("DTCLIENT",dateTimeStr(), ver),
                OfxField("USERID",self.user, ver),
                OfxField("USERPASS",self.password, ver),
                OfxField("LANGUAGE","ENG", ver),
                OfxTag("FI", *fidata),
                OfxField("APPID",FieldVal(site,"APPID"), ver),
                OfxField("APPVER", FieldVal(site,"APPVER"), ver),
                clientuid
                ))
        return rtn

    def _acctreq(self):
        req = OfxTag("ACCTINFORQ",OfxField("DTACCTUP",self.dtacctup))
        return self._message("SIGNUP","ACCTINFO",req)

    def _bareq(self, bankid, acctid, dtstart, acct_type):
        site=self.site
        ver=self.ofxver
        req = OfxTag("STMTRQ",
                OfxTag("BANKACCTFROM",
                OfxField("BANKID",bankid, ver),
                OfxField("ACCTID",acctid, ver),
                OfxField("ACCTTYPE",acct_type, ver)),
                OfxTag("INCTRAN",
                OfxField("DTSTART",dtstart, ver),
                OfxField("INCLUDE","Y", ver))
                )
        return self._message("BANK","STMT",req)
    
    def _ccreq(self, acctid, dtstart):
        site=self.site
        ver  = self.ofxver
        req = OfxTag("CCSTMTRQ",
              OfxTag("CCACCTFROM",OfxField("ACCTID",acctid, ver)),
              OfxTag("INCTRAN",
              OfxField("DTSTART",dtstart, ver),
              OfxField("INCLUDE","Y", ver)))
        return self._message("CREDITCARD","CCSTMT",req)

    def _invstreq(self, brokerid, acctid, dtstart):
        dtnow = time.strftime("%Y%m%d%H%M%S",time.localtime())
        ver  = self.ofxver
        req = OfxTag("INVSTMTRQ",
                OfxTag("INVACCTFROM",
                    OfxField("BROKERID", brokerid, ver),
                    OfxField("ACCTID",acctid, ver)),
                OfxTag("INCTRAN",
                    OfxField("DTSTART",dtstart, ver),
                    OfxField("INCLUDE","Y", ver)),
                OfxField("INCOO","Y", ver),
                OfxTag("INCPOS",
                    OfxField("DTASOF", dtnow, ver),
                    OfxField("INCLUDE","Y", ver)),
                OfxField("INCBAL","Y", ver))
        return self._message("INVSTMT","INVSTMT",req)

    def _message(self,msgType,trnType,request):
        site = self.site
        ver  = self.ofxver
        return OfxTag(msgType+"MSGSRQV1",
               OfxTag(trnType+"TRNRQ",
               OfxField("TRNUID",ofxUUID(), ver),
               request))
    
    def _header(self):
        site = self.site
        if self.ofxver[0]=='2':
            rtn = """<?xml version="1.0" encoding="utf-8" ?>
                     <?OFX OFXHEADER="200" VERSION="%ofxver%" SECURITY="NONE" OLDFILEUID="NONE" NEWFILEUID="NONE"?>"""
            rtn = rtn.replace('%ofxver%', self.ofxver)

        else:
            rtn = join('\r\n',["OFXHEADER:100",
                           "DATA:OFXSGML",
                           "VERSION:" + self.ofxver,
                           "SECURITY:NONE",
                           "ENCODING:USASCII",
                           "CHARSET:1252",
                           "COMPRESSION:NONE",
                           "OLDFILEUID:NONE",
                           "NEWFILEUID:NONE",
                           ""])
        return rtn

    def baQuery(self, bankid, acctid, dtstart, acct_type):
        #Bank account statement request
        return join('\r\n',
                    [self._header(),
                     OfxTag("OFX",
                          self._signOn(),
                          self._bareq(bankid, acctid, dtstart, acct_type)
                          )
                    ]
                )
                        
    def ccQuery(self, acctid, dtstart):
        #CC Statement request
        return join('\r\n',[self._header(),
                    OfxTag("OFX",
                    self._signOn(),
                    self._ccreq(acctid, dtstart))])

    def acctQuery(self):
        return join('\r\n',[self._header(),
                    OfxTag("OFX",
                    self._signOn(),
                    self._acctreq())])

    def invstQuery(self, brokerid, acctid, dtstart):
        return join('\r\n',[self._header(),
                    OfxTag("OFX",
                    self._signOn(),
                    self._invstreq(brokerid, acctid, dtstart))])

    def doQuery(self,query,name):
        response=None
        try:
            errmsg= "** An ERROR occurred attempting HTTPS connection to"
            s = requests.Session() 

            #fiddler env vars config for debug.  HTTPSPROXY auto-recognized by Requests, but not PYTHONHTTPSVERIFY
            #   set PYTHONHTTPSVERIFY=0
            #   set HTTPSPROXY="https://127.0.0.1:8888"
            httpsVerify = False if os.environ.get('PYTHONHTTPSVERIFY','')=='0' else True
            header = collections.OrderedDict()
            header['Content-Type'] = 'application/x-ofx'
            header['Host']         = self.urlHost
            header['Content-Length'] = str(len(query))  #auto-created by requests
            header['Connection']   = 'Keep-Alive'
            header['Accept'] = 'application/x-ofx'
            if self.useragent is None:                   #default
                header['User-Agent'] = 'InetClntApp/3.0'
            elif self.useragent.lower()!='none':
                header['User-Agent'] = self.useragent
            s.headers = header

            for i in [0,1]:
                #retry for sites that require session cookie(s)
                errmsg= "** An ERROR occurred sending POST request to"
                response = s.post(self.url, data=query, verify=httpsVerify)
 
                respDat = response.text.encode('ascii', 'ignore')
                if Debug:
                    log.debug('*** SENT ***')
                    log.debug('HEADER: ' + str(response.request.headers))
                    log.debug(response.request.body)
                    log.debug('*** RECEIVED ***')
                    log.debug('HEADER:' + str(response.headers))
                    log.debug(respDat)

                if validOFX(respDat)=='': break

            if validOFX(respDat)=='': 
                #if this is a OFX 2.x response, replace the header w/ OFX 1.x
                if self.ofxver[0] == '2':
                    respDat = re.sub(r'<\?.*\?>', '', respDat)      #remove xml header lines like <? content...content ?>
                    respDat = OfxSGMLHeader() + respDat.lstrip()

            with open(name,"w") as f:
                f.write(respDat)
            
        except Exception as e:
            self.status = False
            log.exception(errmsg + ' ' + self.url)

            if response:
                log.info('HTTPS ResponseCode  : ' + str(response.status_code))
                log.info('HTTPS ResponseReason: ' + response.reason)

        if response: response.close()       
#------------------------------------------------------------------------------

def getOFX(account, interval):

    sitename   = account[0]
    _acct_num  = account[1]             #account value defined in sites.dat
    acct_type  = account[2]
    user       = account[3]
    password   = account[4]
    acct_num = _acct_num.split(':')[0]  #bank account# (stripped of :xxx version)

    global log
    log = logging.getLogger('root')

    #get site and other user-defined data
    site = userdat.sites[sitename]
    
    #set the interval (days)
    minInterval = FieldVal(site,'mininterval')    #minimum interval (days) defined for this site (optional)
    if minInterval:
         interval = max(minInterval, interval)    #use the longer of the two
    
    #set the start date/time
    dtstart = time.strftime("%Y%m%d",time.localtime(time.time()-interval*86400))
    dtnow = time.strftime("%Y%m%d%H%M%S",time.localtime())

    #add delay prior to connect if defined for site
    delay = FieldVal(site, "DELAY")
    if delay > 0.0: 
        log.info('Delaying %.1f seconds...' % delay)
        time.sleep(delay)

    client = OFXClient(site, user, password)
    log.info('%s: %s: Getting records since: %s' % (sitename,acct_num,dtstart))
    
    status = True
    
    #remove illegal WinFile characters from the file name (in case someone included them in the sitename)
    #Also, the os.system() call doesn't allow the '&' char, so we'll replace it too
    sitename = ''.join(a for a in sitename if a not in ' &\/:*?"!=|()')  #first char is a space
    
    ofxFileSuffix = str(random.randrange(1e5,1e6)) + ".ofx"
    ofxFileName = xfrdir + sitename + dtnow + ofxFileSuffix
    
    try:
        if acct_num == '':
            query = client.acctQuery()
        else:
            caps = FieldVal(site, "CAPS")
            
            if "CCSTMT" in caps:
                query = client.ccQuery(acct_num, dtstart)
            elif "INVSTMT" in caps:
                #if we have a brokerid, use it.  Otherwise, try the fiorg value.
                orgID = FieldVal(site, 'BROKERID')
                if orgID == '': orgID = FieldVal(site, 'FIORG')
                if orgID == '':
                    msg = '** Error: Site', sitename, 'missing (REQUIRED) BrokerID or FIORG value(s).'
                    raise Exception(msg)
                query = client.invstQuery(orgID, acct_num, dtstart)

            elif "BASTMT" in caps:
                bankid = FieldVal(site, "BANKID")
                if bankid == '':
                    msg='** Error: Site', sitename, 'missing (REQUIRED) BANKID value.'
                    raise Exception(msg)
                query = client.baQuery(bankid, acct_num, dtstart, acct_type)

            else:
               msg='** Error: Site', sitename, 'missing (REQUIRED) AcctType value.'
               raise Exception(msg) 

        #do the deed
        client.doQuery(query, ofxFileName)
        if not client.status: return False, ''
        
        #check the ofx file and make sure it looks valid (contains header and <ofx>...</ofx> blocks)
        if glob.glob(ofxFileName) == []:
            status = False  #no ofx file?
        else: 
            f = open(ofxFileName,'r')
            content = f.read().upper()
            f.close

            if acct_num != _acct_num:
                #replace bank account number w/ value defined in sites.dat
                content = content.replace('<ACCTID>'+acct_num, '<ACCTID>'+ _acct_num)
                f = open(ofxFileName,'w')
                f.write(content)
                f.close()
                
            content = ''.join(a for a in content if a not in '\r\n ')  #strip newlines & spaces
            msg = validOFX(content)  #checks for valid format and error messages
            
            if msg != '':
                #throw exception and exit
                raise Exception(msg)
                
            #cleanup the file if needed
            scrubber.scrub(ofxFileName, site)
        
    except Exception as e:
        status = False
        log.exception(msg)

        if glob.glob(ofxFileName) != []:
           log.info('**  Review ' + ofxFileName + ' for possible clues.')
        
    return status, ofxFileName
