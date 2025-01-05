#include<iostream>
#include<conio.h>
using namespace std;
int main()

{
    int i,marks[5];

    for(int i=0;i<5; i++)
    {
      cout<<"Enter marks for sub_"<<i+1<<" is: ";
        cin>>marks[i];
    }
    cout<<endl<<endl;
    cout<<"\t\t\b"<<"Marks are: ";
    for(int i=0; i<5; i++)
    {
        cout<<marks[i]<<"  ";
    }

    getch();
}
