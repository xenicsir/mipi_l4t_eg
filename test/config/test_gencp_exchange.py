#!/usr/bin/env python3
"""Exercise the real atomic GenCP API with binary memory and malformed callers."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT/'sources/common/source/nvidia-oot/drivers/media/i2c/gencp-over-i2c'
SOURCE = r'''
#include <assert.h>
#include <errno.h>
#include <string.h>
#include <stdio.h>
#include "gencp_common.h"
#include "gencp_client.h"
static unsigned calls;
static uint64_t last_address;
static unsigned char memory[1008];
static unsigned short reply_status;
static unsigned short checksum(unsigned char *p, unsigned n) {
 unsigned sum=0;for(unsigned i=0;i<n;i++)sum+=p[i]<<((i&1)?0:8);
 while(sum>>16)sum=(sum&65535)+(sum>>16);
 return sum==65535?65535:(unsigned short)~sum;
}
static void put(unsigned char *p,unsigned v){p[0]=v>>8;p[1]=v;}
static unsigned get(unsigned char *p){return (p[0]<<8)|p[1];}
static void crc(struct eg_gencp_xfer *x){put(x->tx+2,checksum(x->tx+6,10));put(x->tx+4,checksum(x->tx+6,x->tx_length-6));}
static void request(struct eg_gencp_xfer *x,unsigned cmd,unsigned n,uint64_t address){
 memset(x,0,sizeof(*x));x->version=1;x->rx_capacity=1024;
 x->tx_length=cmd==0x800?28:24+n;
 x->tx[0]=1;put(x->tx+8,0x4000);put(x->tx+10,cmd);put(x->tx+12,x->tx_length-16);put(x->tx+14,0x1234);
 for(unsigned i=0;i<8;i++)x->tx[23-i]=address>>(i*8);
 if(cmd==0x800)put(x->tx+26,n);else memcpy(x->tx+24,memory,n);
 crc(x);
}
static unsigned short rd(void *p,uint64_t address,unsigned char *data,unsigned short n){
 (void)p;calls++;last_address=address;memcpy(data,memory,n);return reply_status;
}
static unsigned short wr(void *p,uint64_t address,const unsigned char *data,unsigned short n){
 (void)p;calls++;last_address=address;assert(!memcmp(data,memory,n));return reply_status;
}
struct peer { unsigned char ack[1024]; unsigned writes; uint16_t id; uint8_t value; };
static void custom_begin(struct unio_handle *h){(void)h;}
static int custom_send(struct unio_handle *h,const unsigned char *data,size_t n){
 struct peer *p=h->transport_private;(void)n;
 p->writes++;assert(get((unsigned char *)data+14)==p->writes);p->id=get((unsigned char *)data+14);
 memset(p->ack,0,sizeof(p->ack));p->ack[0]=1;
 put(p->ack+10,get((unsigned char *)data+10)+1);put(p->ack+14,p->id);
 unsigned length=get((unsigned char *)data+26);put(p->ack+12,length);
 memset(p->ack+16,p->value,length);
 put(p->ack+2,checksum(p->ack+6,10));put(p->ack+4,checksum(p->ack+6,10+length));return 0;
}
static int custom_read(struct unio_handle *h,unsigned char *data,size_t capacity){
 struct peer *p=h->transport_private;assert(capacity==1024);memcpy(data,p->ack,capacity);return 1;
}
static const struct gencp_transport_ops custom_ops={48,700,custom_begin,custom_send,custom_read};
int main(void){
 struct eg_gencp_xfer x;struct unio_handle h={0};unsigned before;
 assert(sizeof(x)==2080&&sizeof(struct eg_gencp_stats)==40);
 for(unsigned i=0;i<1008;i++)memory[i]=i;
 for(unsigned n=1;n<=1008;n++){
  request(&x,0x800,n,0x123456789abcULL);
  assert(!GENCPCLIENT_Exchange(&h,&x,0,rd,wr));assert(x.rx_length==16+n);
  assert(last_address==0x123456789abcULL&&!memcmp(x.rx+16,memory,n));
  assert(get(x.rx+14)==0x1234&&get(x.rx+10)==0x801);
  assert(get(x.rx+2)==checksum(x.rx+6,10)&&get(x.rx+4)==checksum(x.rx+6,10+n));
 }
 for(unsigned n=1;n<=1000;n++){
  request(&x,0x802,n,0x9000000000ULL);
  assert(!GENCPCLIENT_Exchange(&h,&x,0,rd,wr));assert(x.rx_length==20);
  assert(get(x.rx+18)==n&&get(x.rx+10)==0x803);
  assert(get(x.rx+4)==checksum(x.rx+6,14));
 }
 before=calls;request(&x,0x802,4,0);x.rx_capacity=19;
 assert(GENCPCLIENT_Exchange(&h,&x,0,rd,wr)==-ENOSPC&&calls==before);
 request(&x,0x800,1008,0);x.rx_capacity=1023;
 assert(GENCPCLIENT_Exchange(&h,&x,0,rd,wr)==-ENOSPC&&calls==before);
 request(&x,0x800,0,0);assert(GENCPCLIENT_Exchange(&h,&x,0,rd,wr)==-EMSGSIZE);
 request(&x,0x800,1009,0);assert(GENCPCLIENT_Exchange(&h,&x,0,rd,wr)==-EMSGSIZE);
 request(&x,0x800,8,~(uint64_t)0);assert(GENCPCLIENT_Exchange(&h,&x,0,rd,wr)==-EINVAL);
 request(&x,0x800,4,0);x.tx_length=15;assert(GENCPCLIENT_Exchange(&h,&x,0,rd,wr)==-EBADMSG);
 request(&x,0x800,4,0);x.tx[2]^=1;assert(GENCPCLIENT_Exchange(&h,&x,0,rd,wr)==-EBADMSG);
 request(&x,0x800,4,0);x.tx[4]^=1;assert(GENCPCLIENT_Exchange(&h,&x,0,rd,wr)==-EBADMSG);
 request(&x,0x800,4,0);put(x.tx+6,1);crc(&x);assert(GENCPCLIENT_Exchange(&h,&x,0,rd,wr)==-EOPNOTSUPP);
 request(&x,0x800,4,0);put(x.tx+10,0x805);crc(&x);assert(GENCPCLIENT_Exchange(&h,&x,0,rd,wr)==-EOPNOTSUPP);
 request(&x,0x800,4,0);x.version=2;assert(GENCPCLIENT_Exchange(&h,&x,0,rd,wr)==-EINVAL);
 request(&x,0x800,4,0);x.reserved[2]=1;assert(GENCPCLIENT_Exchange(&h,&x,0,rd,wr)==-EINVAL);
 request(&x,0x800,4,0);x.rx_length=1;assert(GENCPCLIENT_Exchange(&h,&x,0,rd,wr)==-EINVAL);
 request(&x,0x800,4,0);x.flags=1;assert(GENCPCLIENT_Exchange(&h,&x,0,rd,wr)==-EINVAL);
 assert(calls==before);
 request(&x,0x800,4,0);reply_status=0x8003;
 assert(!GENCPCLIENT_Exchange(&h,&x,0,rd,wr));assert(x.rx_length==16&&get(x.rx+8)==0x8003);
 for(unsigned i=16;i<1024;i++)assert(!x.rx[i]);
 struct unio_handle a={0},b={0};struct peer pa={.value=0x12},pb={.value=0x34};unsigned char data[4];
 assert(!GENCPCLIENT_SetTransport(&a,&custom_ops,&pa));assert(!GENCPCLIENT_SetTransport(&b,&custom_ops,&pb));
 assert(!GENCPCLIENT_ReadMemory(&a,0x100000000ULL,data,4)&&data[0]==0x12);
 assert(!GENCPCLIENT_ReadMemory(&b,0x200000000ULL,data,4)&&data[0]==0x34);
 GENCPCLIENT_Select(&a);uint32_t value;
 assert(!GENCPCLIENT_ReadRegister(0,&value)&&value==0x12121212);
 request(&x,0x800,4,0);put(x.tx+14,0);crc(&x);
 assert(!GENCPCLIENT_Exchange(&b,&x,0,0,0)&&get(x.rx+14)==0&&x.rx[16]==0x34);
 assert(pa.writes==2&&pb.writes==2&&a.gencp.request_id==2&&b.gencp.request_id==2);
 assert(!GENCPCLIENT_ReadRegister(0,&value)&&value==0x12121212);
 assert(GENCPCLIENT_SetTransport(0,&custom_ops,0)==-EINVAL); /* NULL handle rejected. */
 puts("GenCP exchange: bounds, CRC, IDs, binary data, contexts and custom transport OK");return 0;
}
'''

class ExchangeTests(unittest.TestCase):
    def test_real_exchange_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp);(path/'peer.c').write_text(SOURCE)
            cmd=['cc','-std=gnu11','-Wall','-Wextra','-Werror','-Wno-unused-const-variable','-Wno-unused-parameter',
                 '-fsanitize=address,undefined','-fno-pie','-no-pie','-I'+str(LIB),str(path/'peer.c')]
            cmd += [str(LIB/name) for name in ('gencp_client.c','gencp_transport.c','gencp_common.c','libunio.c')]
            cmd+=['-o',str(path/'peer')]
            subprocess.run(cmd,check=True);subprocess.run([str(path/'peer')],check=True)

if __name__=='__main__':unittest.main()
