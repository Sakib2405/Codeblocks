#include<iostream>
#include<conio.h>
using namespace std;
// Area of a Rectangle
int main()
{
    int length, width, Area;

    cout<<"Enter the length: ";
      cin>>length;
    cout<<"Enter the width: ";
    cin>>width;

    Area=length*width;

    cout<<"The area of Rectangle: " <<Area;

    getch();
}
