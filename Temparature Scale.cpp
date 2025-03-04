#include<iostream>
#include<conio.h>
using namespace std;
main()
{
    double C, temp;

    cout<<"Enter the value of Celcius Scale: ";
    cin>>C;

    temp=((C*9)/5)+32;
    cout<<"The converted temparature is: "<<temp;

    getch();
}
