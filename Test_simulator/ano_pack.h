// ano_pack.h
#ifndef ANO_PACK_H
#define ANO_PACK_H

#include <stdint.h>

#define BYTE0(dwTemp)       ( *( (uint8_t *)(&dwTemp)      ) )
#define BYTE1(dwTemp)       ( *( (uint8_t *)(&dwTemp) + 1) )
#define BYTE2(dwTemp)       ( *( (uint8_t *)(&dwTemp) + 2) )
#define BYTE3(dwTemp)       ( *( (uint8_t *)(&dwTemp) + 3) )


static uint8_t data_to_send[64];
static int data_len_Attitude;
static int data_len_Sensor;
static int data_len_Servo;

// 发送姿态数据
uint8_t* ANO_Send_Attitude(float angle_rol, float angle_pit, float angle_yaw, float roll_6,float pitch_6,float yaw_6, int32_t alt, uint8_t fly_model, uint8_t armed)
{
    uint8_t _cnt = 0;
    int16_t _temp;

    data_to_send[_cnt++] = 0xAA; // 帧头
    data_to_send[_cnt++] = 0xAA; // 帧头
    data_to_send[_cnt++] = 0x01; // 功能字
    data_to_send[_cnt++] = 0;    // 数据长度

    _temp = (int16_t)(angle_rol * 100);
    data_to_send[_cnt++] = BYTE1(_temp);
    data_to_send[_cnt++] = BYTE0(_temp);
    _temp = (int16_t)(angle_pit * 100);
    data_to_send[_cnt++] = BYTE1(_temp);
    data_to_send[_cnt++] = BYTE0(_temp);
    _temp = (int16_t)(angle_yaw * 100);
    data_to_send[_cnt++] = BYTE1(_temp);
    data_to_send[_cnt++] = BYTE0(_temp);
    _temp = (int16_t)(roll_6 * 100);
    data_to_send[_cnt++] = BYTE1(_temp);
    data_to_send[_cnt++] = BYTE0(_temp);
    _temp = (int16_t)(pitch_6 * 100);
    data_to_send[_cnt++] = BYTE1(_temp);
    data_to_send[_cnt++] = BYTE0(_temp);
    _temp = (int16_t)(yaw_6 * 100);
    data_to_send[_cnt++] = BYTE1(_temp);
    data_to_send[_cnt++] = BYTE0(_temp);

    data_to_send[_cnt++] = BYTE3(alt);
    data_to_send[_cnt++] = BYTE2(alt);
    data_to_send[_cnt++] = BYTE1(alt);
    data_to_send[_cnt++] = BYTE0(alt);

    data_to_send[_cnt++] = fly_model;
    data_to_send[_cnt++] = armed;



    data_to_send[3] = _cnt - 4;

    // 计算校验和
    uint8_t sum = 0;
    for (uint8_t i = 0; i < _cnt; i++)
    {
        sum += data_to_send[i];
    }
    data_to_send[_cnt++] = sum;


    data_len_Attitude = _cnt;
    return data_to_send;
}

// 发送传感器数据
uint8_t* ANO_Send_Sensor(float a_x, float a_y, float a_z,float g_x, float g_y, float g_z, float m_x, float m_y, float m_z,float q0,float q1, float q2, float q3,float mx, float my, float mz)
{
    uint8_t _cnt = 0;
    int16_t _temp;

    data_to_send[_cnt++] = 0xAA; // 帧头
    data_to_send[_cnt++] = 0xAA; // 帧头
    data_to_send[_cnt++] = 0x02; // 功能字
    data_to_send[_cnt++] = 0;    // 数据长度

    _temp = (int16_t)(a_x*100);
    data_to_send[_cnt++] = BYTE1(_temp);
    data_to_send[_cnt++] = BYTE0(_temp);
    _temp = (int16_t)(a_y*100);
    data_to_send[_cnt++] = BYTE1(_temp);
    data_to_send[_cnt++] = BYTE0(_temp);
    _temp = (int16_t)(a_z*100);
    data_to_send[_cnt++] = BYTE1(_temp);
    data_to_send[_cnt++] = BYTE0(_temp);
    _temp = (int16_t)(g_x*100);
    data_to_send[_cnt++] = BYTE1(_temp);
    data_to_send[_cnt++] = BYTE0(_temp);
    _temp = (int16_t)(g_y*100);
    data_to_send[_cnt++] = BYTE1(_temp);
    data_to_send[_cnt++] = BYTE0(_temp);
    _temp = (int16_t)(g_z*100);
    data_to_send[_cnt++] = BYTE1(_temp);
    data_to_send[_cnt++] = BYTE0(_temp);
    _temp = (int16_t)(m_x*100);
    data_to_send[_cnt++] = BYTE1(_temp);
    data_to_send[_cnt++] = BYTE0(_temp);
    _temp = (int16_t)(m_y*100);
    data_to_send[_cnt++] = BYTE1(_temp);
    data_to_send[_cnt++] = BYTE0(_temp);
    _temp = (int16_t)(m_z*100);
    data_to_send[_cnt++] = BYTE1(_temp);
    data_to_send[_cnt++] = BYTE0(_temp);
    _temp = (int16_t)(q0*100);
    data_to_send[_cnt++] = BYTE1(_temp);
    data_to_send[_cnt++] = BYTE0(_temp);
    _temp = (int16_t)(q1*100);
    data_to_send[_cnt++] = BYTE1(_temp);
    data_to_send[_cnt++] = BYTE0(_temp);
    _temp = (int16_t)(q2*100);
    data_to_send[_cnt++] = BYTE1(_temp);
    data_to_send[_cnt++] = BYTE0(_temp);
    _temp = (int16_t)(q3*100);
    data_to_send[_cnt++] = BYTE1(_temp);
    data_to_send[_cnt++] = BYTE0(_temp);
    _temp = (int16_t)(mx*100);
    data_to_send[_cnt++] = BYTE1(_temp);
    data_to_send[_cnt++] = BYTE0(_temp);
    _temp = (int16_t)(my*100);
    data_to_send[_cnt++] = BYTE1(_temp);
    data_to_send[_cnt++] = BYTE0(_temp);
    _temp = (int16_t)(mz*100);
    data_to_send[_cnt++] = BYTE1(_temp);
    data_to_send[_cnt++] = BYTE0(_temp);

    // data_to_send[_cnt++] = BYTE1(a_x);
    // data_to_send[_cnt++] = BYTE0(a_x);
    // data_to_send[_cnt++] = BYTE1(a_y);
    // data_to_send[_cnt++] = BYTE0(a_y);
    // data_to_send[_cnt++] = BYTE1(a_z);
    // data_to_send[_cnt++] = BYTE0(a_z);

    // data_to_send[_cnt++] = BYTE1(g_x);
    // data_to_send[_cnt++] = BYTE0(g_x);
    // data_to_send[_cnt++] = BYTE1(g_y);
    // data_to_send[_cnt++] = BYTE0(g_y);
    // data_to_send[_cnt++] = BYTE1(g_z);
    // data_to_send[_cnt++] = BYTE0(g_z);

    // data_to_send[_cnt++] = BYTE1(m_x);
    // data_to_send[_cnt++] = BYTE0(m_x);
    // data_to_send[_cnt++] = BYTE1(m_y);
    // data_to_send[_cnt++] = BYTE0(m_y);
    // data_to_send[_cnt++] = BYTE1(m_z);
    // data_to_send[_cnt++] = BYTE0(m_z);

    data_to_send[3] = _cnt - 4;

    // 计算校验和
    uint8_t sum = 0;
    for (uint8_t i = 0; i < _cnt; i++)
    {
        sum += data_to_send[i];
    }
    data_to_send[_cnt++] = sum;


    data_len_Sensor = _cnt;
    return data_to_send;
}


/**
 * @brief 按照匿名的传输方式自定义的一个传输舵机数据的函数，但是无法和匿名上位机通信
 * @param leftpwm 左舵机PWM值
 * @param leftdeg 左舵机角度
 * @param rightpwm 右舵机PWM值
 * @param rightdeg 右舵机角度
 */
uint8_t* ANO_Send_Servo_Data(float leftpwm, float leftdeg, float rightpwm, float rightdeg,float pm,float speed,float height,float data4 )
{
    uint8_t _cnt = 0;
    int16_t _temp;

    data_to_send[_cnt++] = 0xAA; // 帧头
    data_to_send[_cnt++] = 0xAA; // 帧头
    data_to_send[_cnt++] = 0xF3; // 功能字，改为0x03
    data_to_send[_cnt++] = 0;    // 数据长度

    // 发送第一个数据
    _temp = (int16_t)(leftpwm );
    data_to_send[_cnt++] = BYTE1(_temp);
    data_to_send[_cnt++] = BYTE0(_temp);

    // 发送第二个数据
    _temp = (int16_t)(leftdeg * 100);
    data_to_send[_cnt++] = BYTE1(_temp);
    data_to_send[_cnt++] = BYTE0(_temp);

    // 发送第三个数据
    _temp = (int16_t)(rightpwm);
    data_to_send[_cnt++] = BYTE1(_temp);
    data_to_send[_cnt++] = BYTE0(_temp);

    // 发送第四个数据
    _temp = (int16_t)(rightdeg * 100);
    data_to_send[_cnt++] = BYTE1(_temp);
    data_to_send[_cnt++] = BYTE0(_temp);

    // 发送第五个数据
    _temp = (int16_t)(pm);
    data_to_send[_cnt++] = BYTE1(_temp);
    data_to_send[_cnt++] = BYTE0(_temp);

    // 发送第六个数据
    _temp = (int16_t)(speed * 100);
    data_to_send[_cnt++] = BYTE1(_temp);
    data_to_send[_cnt++] = BYTE0(_temp);

    // 发送第七个数据
    _temp = (int16_t)(height * 100);
    // Serial.println(_temp);
    data_to_send[_cnt++] = BYTE1(_temp);
    data_to_send[_cnt++] = BYTE0(_temp);

    // 发送第八个数据
    _temp = (int16_t)(data4);
    data_to_send[_cnt++] = BYTE1(_temp);
    data_to_send[_cnt++] = BYTE0(_temp);



    data_to_send[3] = _cnt - 4;

    // 计算校验和
    uint8_t sum = 0;
    for (uint8_t i = 0; i < _cnt; i++)
    {
        sum += data_to_send[i];
    }
    data_to_send[_cnt++] = sum;

    data_len_Servo = _cnt;
    return data_to_send;
}



#endif
