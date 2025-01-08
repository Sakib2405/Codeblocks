/*

#include<iostream>
#include<conio.h>
using namespace std;

int main()

{
    double temp,F;

    cout<<"Enter the temparature of Farenheight scale: ";

    cin>>F;

    temp=(F-32)/1.8;
    cout<<endl<<"The converted tempatarue in Celsius scale: "<<temp;

    getch();
}

*/

#include<iostream>
#include<conio.h>
using namespace std;
int main()
{
  double F, temp;
  cout<<"Enter the value of farenheight scale: ";
  cin>> F;
  temp= ((F-32)*5)/9;
  cout<<endl<< "The converted temparature in Celcius scale :"<<temp;
getch();

}
